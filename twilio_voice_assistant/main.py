import os
import base64
import io
import logging
import wave
import audioop
import pywav
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from twilio.twiml.voice_response import VoiceResponse, Connect
from sarvamai import SarvamAI
from dotenv import load_dotenv
from nnmnkwii.preprocessing import mulaw_quantize, inv_mulaw_quantize, mulaw, inv_mulaw
from datetime import datetime
from scipy.signal import resample
from tempfile import NamedTemporaryFile
import tempfile
# from scikits.audiolab import Sndfile

# --- Configuration ---
# Load environment variables from .env file
# Create a .env file in the same directory and add your keys
# SARVAM_API_KEY="your_sarvam_api_key"
# TWILIO_ACCOUNT_SID="your_twilio_account_sid"
# TWILIO_AUTH_TOKEN="your_twilio_auth_token"
load_dotenv()

# Get credentials from environment
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI()

# Initialize SarvamAI client
try:
    sarvam_client = SarvamAI(api_subscription_key=SARVAM_API_KEY)
    logger.info("SarvamAI client initialized successfully.")
except Exception as e:
    logger.error(f"Failed to initialize SarvamAI client: {e}")
    sarvam_client = None

# --- Twilio Webhook for Incoming Calls ---
@app.post("/incoming_call")
async def handle_incoming_call(response: Response):
    """
    Handles incoming calls from Twilio.
    Responds with TwiML to connect the call to our WebSocket stream.
    """
    logger.info("Incoming call received")
    twiml_response = VoiceResponse()
    
    # The <Connect> verb will establish a media stream
    # The 'url' should point to your WebSocket endpoint
    # Note: For local development, you'll need to use a tool like ngrok
    # to expose your local server to the internet.
    # The URL would look like: wss://<your-ngrok-subdomain>.ngrok.io/ws
    connect = Connect()
    # IMPORTANT: Replace the example URL below with your actual ngrok forwarding URL.
    # Make sure to use 'wss' for a secure WebSocket connection.
    connect.stream(url="wss://bc27-14-143-179-90.ngrok-free.app/ws")
    twiml_response.append(connect)
    
    logger.info("Responding with TwiML to connect to WebSocket.")
    
    return Response(content=str(twiml_response), media_type="application/xml")

# --- WebSocket for Bidirectional Audio Streaming ---
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    Handles the bidirectional audio stream with Twilio.
    """
    await websocket.accept()
    logger.info("WebSocket connection established with Twilio.")
    audio_buffer = bytearray()
    stream_sid = None
    
    try:
        while True:
            message = await websocket.receive_json()
            event = message.get("event")

            if event == "start":
                stream_sid = message["start"]["streamSid"]
                logger.info(f"Twilio media stream started (SID: {stream_sid}).")

            elif event == "media":
                payload = message["media"]["payload"]
                audio_data = base64.b64decode(payload)
                audio_buffer.extend(audio_data)

                # 8000 bytes = 1 second for 8-bit, 8000Hz, 1-channel audio
                if len(audio_buffer) > 24000: # Process after ~3 seconds of audio
                    logger.info(f"Buffer full ({len(audio_buffer)} bytes), processing audio...")
                    
                    # --- Start of Conversational Loop ---
                    
                    # 1. Prepare audio data for transcription
                    wav_bytes = convert_mulaw_to_wav_bytes(bytes(audio_buffer))
                    
                    if wav_bytes:
                        # 2. Transcribe audio to text
                        transcription = transcribe_audio(wav_bytes)
                        if transcription and transcription.transcript:
                            # 3. Get a response from the LLM
                            logger.info(f"LLM INPUT (Transcription): {transcription.transcript}")
                            llm_response_text = get_llm_response(transcription.transcript)
                            
                            if llm_response_text:
                                logger.info(f"LLM OUPUT (Response): {llm_response_text}")
                                
                                # 4. Convert the LLM's text response to speech
                                response_audio_wav = convert_text_to_speech(llm_response_text)

                                if response_audio_wav:
                                    # --- Start of Comprehensive Outgoing Audio Logging ---
                                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

                                    # Log the original, clean WAV from the TTS service
                                    tts_log_filename = f"outgoing_audio_logs/tts_output_{timestamp}.wav"
                                    with open(tts_log_filename, "wb") as log_file:
                                        log_file.write(response_audio_wav)
                                    logger.info(f"Saved original TTS audio to: {tts_log_filename}")

                                    # 5. Convert response audio to raw mulaw bytes for Twilio
                                    response_audio_mulaw = convert_wav_to_mulaw_bytes(response_audio_wav)
                                    
                                    if response_audio_mulaw:
                                        # Log the final raw mulaw bytestream being sent to Twilio
                                        mulaw_log_filename = f"outgoing_audio_logs/twilio_stream_{timestamp}.ulaw"
                                        with open(mulaw_log_filename, "wb") as log_file:
                                            log_file.write(response_audio_mulaw)
                                        logger.info(f"Saved final mulaw stream to: {mulaw_log_filename}")

                                        # 6. Send audio back to Twilio
                                        payload = base64.b64encode(response_audio_mulaw).decode("utf-8")
                                        
                                        # --- Start of Final Verification Log ---
                                        logger.info("Preparing to send media response to Twilio.")
                                        logger.info(f"  - Event: media")
                                        logger.info(f"  - Stream SID: {stream_sid}")
                                        logger.info(f"  - Payload Length (chars): {len(payload)}")
                                        # --- End of Final Verification Log ---
                                        
                                        await websocket.send_json({
                                            "event": "media",
                                            "streamSid": stream_sid,
                                            "media": {
                                                "payload": payload
                                            }
                                        })
                                        logger.info("Sent audio response back to Twilio.")

                    # --- End of Conversational Loop ---
                    
                    # Clear buffer after processing
                    audio_buffer.clear()

            elif event == "stop":
                logger.info("Twilio media stream stopped.")
                # Process any remaining audio in the buffer to catch the last words.
                if audio_buffer:
                    logger.info("Processing remaining audio in buffer on stop event.")
                    wav_bytes = convert_mulaw_to_wav_bytes(bytes(audio_buffer))
                    if wav_bytes:
                        transcription = transcribe_audio(wav_bytes)
                        if transcription and transcription.transcript:
                            # We'll just log the final transcription and not send a response,
                            # as the stream is closing.
                            logger.info(f"Final transcription: {transcription.transcript}")
                    audio_buffer.clear()
                break
                
    except WebSocketDisconnect:
        logger.warning("WebSocket disconnected.")
    except Exception as e:
        logger.error(f"Error in WebSocket: {e}", exc_info=True)
    finally:
        logger.info("Closing WebSocket connection.")

# --- Audio Conversion Utilities ---

def convert_mulaw_to_wav_bytes(mulaw_bytes: bytes) -> bytes:
    """
    Packages raw mulaw bytes from Twilio into a WAV file container.
    This does NOT decode the audio, it just puts the raw bytes in a recognizable format.
    """
    try:
        # pywav needs to write to a real file, so we use a temporary file.
        with NamedTemporaryFile(suffix=".wav", delete=True) as tmpfile:
            wave_write = pywav.WavWrite(tmpfile.name, 1, 8000, 8, 7)  # 7 = µ-law encoding
            wave_write.write(mulaw_bytes)
            wave_write.close()
            
            # Read the bytes from the temporary file we just created
            tmpfile.seek(0)
            wav_bytes = tmpfile.read()
        
        return wav_bytes
    except Exception as e:
        logger.error(f"Failed to convert mulaw to wav: {e}", exc_info=True)
        return None

def convert_wav_to_mulaw_bytes(wav_bytes: bytes) -> bytes:
    """
    Converts a standard 16-bit PCM WAV file into raw, headerless 8kHz µ-law
    bytes suitable for the Twilio media stream, using the standard audioop library.
    """
    try:
        # 1. Read the raw PCM audio frames from the WAV file bytes
        with wave.open(io.BytesIO(wav_bytes), 'rb') as wf:
            # Ensure audio is 16-bit mono PCM, which is what lin2ulaw expects.
            if wf.getsampwidth() != 2 or wf.getnchannels() != 1:
                logger.error(
                    f"Unsupported WAV format: "
                    f"Sample width {wf.getsampwidth()}, channels {wf.getnchannels()}. "
                    f"Expected 16-bit mono."
                )
                return None
            
            # The TTS service should already provide 8kHz, but we log a warning if not.
            if wf.getframerate() != 8000:
                logger.warning(f"WAV sample rate is {wf.getframerate()}, not 8000Hz.")

            pcm_frames = wf.readframes(wf.getnframes())

        # 2. Convert the 16-bit linear PCM data to 8-bit µ-law.
        # The '2' indicates the sample width of the input data is 2 bytes (16-bit).
        mulaw_bytes = audioop.lin2ulaw(pcm_frames, 2)
        
        return mulaw_bytes

    except Exception as e:
        logger.error(f"Failed to convert wav to mulaw: {e}", exc_info=True)
        return None

# --- SarvamAI Speech-to-Text Function (adapted from your script) ---
def transcribe_audio(audio_bytes: bytes):
    """
    Transcribe audio using SarvamAI's speech translation API.
    Note: Twilio sends audio in mulaw format. SarvamAI might need a different
    format like WAV. We may need to add a conversion step here.
    """
    if not sarvam_client:
        logger.error("SarvamAI client not available.")
        return None

    logger.info("Sending audio to SarvamAI for transcription.")
    try:
        # --- Start of Debugging Block ---
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        log_filename = f"audio_logs/transcription_input_{timestamp}.wav"
        
        # Use the pywav writer for high-fidelity logging
        wave_write = pywav.WavWrite(log_filename, 1, 8000, 8, 7) # 7 = µ-law
        wave_write.write(audio_bytes)
        wave_write.close()

        logger.info(f"Saved audio for debugging to: {log_filename}")
        # --- End of Debugging Block ---

        # The API needs a file-like object.
        # We now pass the properly containerized WAV bytes
        audio_file_like = io.BytesIO(convert_mulaw_to_wav_bytes(audio_bytes))
        # We now have a WAV file, so we name it accordingly.
        audio_file_like.name = "audio.wav" 

        # IMPORTANT: This is the speech-to-text model.
        response = sarvam_client.speech_to_text.translate(
            file=audio_file_like,
            model="saaras:v2.5" 
        )
        logger.info(f"Received transcription: {response}")
        return response
            
    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        return None

# --- SarvamAI Language Model (LLM) Function ---
def get_llm_response(text: str):
    """Get a response from SarvamAI's Chat Completion model."""
    if not sarvam_client:
        logger.error("SarvamAI client not available.")
        return "The AI model is currently unavailable. Please try again later."
    
    messages = [
        {"role": "system", "content": "You are a helpful and concise assistant speaking on a phone call."},
        {"role": "user", "content": text}
    ]
    
    logger.info(f"Sending to LLM: {text}")
    try:
        # Based on SarvamAI documentation, the 'model' parameter is not used in the Python SDK
        response = sarvam_client.chat.completions(
            messages=messages,
            max_tokens=100,
            temperature=0.7,
        )
        content = response.choices[0].message.content
        logger.info(f"Received from LLM: {content}")
        return content
    except Exception as e:
        logger.error(f"LLM request failed: {e}")
        return "I'm sorry, I had trouble generating a response."

# --- SarvamAI Text-to-Speech (TTS) Function ---
def convert_text_to_speech(text: str):
    """Converts text to speech using SarvamAI and returns WAV audio bytes."""
    if not sarvam_client:
        logger.error("SarvamAI client not available.")
        return None
    
    logger.info(f"Sending to TTS: {text}")
    try:
        response = sarvam_client.text_to_speech.convert(
            text=text,
            target_language_code="en-IN",
            speaker="anushka", # Switched to a compatible speaker for bulbul:v2
            model="bulbul:v2",
            speech_sample_rate=8000 # Request 8kHz directly for Twilio
        )
        # The response contains the audio as a list of base64 encoded strings.
        # We take the first element as we only send one text input.
        audio_base64 = response.audios[0]
        wav_bytes = base64.b64decode(audio_base64)
        logger.info("Received TTS audio from SarvamAI.")
        return wav_bytes
    except Exception as e:
        logger.error(f"TTS request failed: {e}")
        return None

# --- Main execution ---
if __name__ == "__main__":
    import uvicorn
    logger.info("Starting FastAPI server.")
    # To run this app:
    # 1. Make sure you have a .env file with your credentials.
    # 2. In your terminal, run: uvicorn main:app --reload
    # 3. Use ngrok to expose your local port 8000 to the web.
    uvicorn.run(app, host="0.0.0.0", port=8000) 