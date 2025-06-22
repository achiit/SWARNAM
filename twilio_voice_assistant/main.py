import os
import base64
import io
import logging
import wave
import audioop
import pywav
import requests
import json
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
TOOLS_API_BASE_URL = os.getenv("TOOLS_API_BASE_URL")
SPLITWISE_API_KEY = os.getenv("SPLITWISE_API_KEY")
CASHFREE_CLIENT_ID = os.getenv("CASHFREE_CLIENT_ID")
CASHFREE_CLIENT_SECRET = os.getenv("CASHFREE_CLIENT_SECRET")

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
    connect.stream(url="wss://ffdb-14-143-179-90.ngrok-free.app/ws")
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
                            # CORRECTED: Get the detected language from the STT response using the correct attribute 'language_code'.
                            # We default to 'en-IN' if the language code is not available.
                            detected_language = getattr(transcription, 'language_code', 'en-IN')
                            logger.info(f"Detected language: {detected_language}")

                            # 3. Get a response from the LLM
                            logger.info(f"LLM INPUT (Transcription): {transcription.transcript}")
                            llm_response_text = get_llm_response(
                                transcription.transcript,
                                language_code=detected_language
                            )
                            
                            if llm_response_text:
                                logger.info(f"LLM OUPUT (Response): {llm_response_text}")
                                
                                # 4. Convert the LLM's text response to speech
                                # NEW: Pass the detected language to the TTS function.
                                response_audio_wav = convert_text_to_speech(
                                    llm_response_text,
                                    language_code=detected_language
                                )

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

# --- Tool Definitions and Execution ---

def summarize_expenses(expenses: list, limit: int = 15) -> list:
    """
    Summarizes a list of expenses based on the new API format, returning
    the key details for the most recent transactions, including emails.
    """
    summary = []
    # Process the most recent expenses up to the limit
    for expense in expenses[:limit]:
        summary.append({
            "description": expense.get('description'),
            "amount": expense.get('amount'),
            "currency": expense.get('currency_code'),
            "date": expense.get('date', '').split('T')[0],
            "from_user": expense.get('from'),
            "from_email": expense.get('from_email'),
            "to_user": expense.get('to'),
            "to_email": expense.get('to_email'),
            "settled": expense.get('settled')
        })
    return summary

# Define the schema for the tools the LLM can use.
# This tells the model what functions are available, what they do, and what parameters they take.
TOOLS = [
    {
        "name": "get_current_user",
        "description": "Fetches the details of the currently authenticated user from Splitwise. Use this to find out who the user is, their name, or their user ID.",
        "parameters": []
    },
    {
        "name": "get_expenses",
        "description": "Fetches a list of recent expenses. Use this when the user asks about their recent transactions, bills, or what they've spent money on.",
        "parameters": []
    },
    {
        "name": "initiate_payment",
        "description": "Starts the process of paying an outstanding expense to a specific person. Use this when the user wants to settle a debt or pay someone.",
        "parameters": [
            {"name": "recipient_name", "type": "string", "description": "The name of the person to pay."}
        ]
    }
]

def _get_current_user_identity() -> dict:
    """Internal helper to fetch the current user's details."""
    logger.info("Fetching current user identity...")
    url = f"{TOOLS_API_BASE_URL}/tools/getCurrentUser"
    headers = {
        'x-splitwise-key': f'{SPLITWISE_API_KEY}',
        'Content-Type': 'application/json'
    }
    try:
        response = requests.post(url, headers=headers, data='{}')
        response.raise_for_status()
        user_data = response.json()
        return user_data.get('data', {}).get('result', {}).get('user', {})
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch current user identity: {e}")
        return {}

def call_tool(tool_name: str, parameters: dict):
    """
    Executes the appropriate API call based on the tool name provided by the LLM.
    """
    if tool_name == "get_current_user":
        logger.info("Executing tool: get_current_user")
        user_identity = _get_current_user_identity()
        if not user_identity:
            return json.dumps({"error": "Could not retrieve current user's identity."})
        
        # We wrap it in the same structure as other tools for consistency
        user_data = {"success": True, "data": {"result": {"user": user_identity}}}
        logger.info(f"Tool 'get_current_user' returned: {user_data}")
        return json.dumps(user_data)
    
    elif tool_name == "get_expenses":
        logger.info("Executing tool: get_expenses")
        url = f"{TOOLS_API_BASE_URL}/tools/getExpenses"
        headers = {
            'x-splitwise-key': f'{SPLITWISE_API_KEY}',
            'Content-Type': 'application/json'
        }
        try:
            response = requests.post(url, headers=headers, data='{}')
            response.raise_for_status()
            expenses_data = response.json()
            logger.info(f"Tool 'get_expenses' returned: {expenses_data}")
            logger.info(f"Tool 'get_expenses' returned successfully with {len(expenses_data.get('data', {}).get('result', {}).get('expenses', []))} expenses.")
            
            # Pre-process the data before sending to the LLM
            expenses_list = expenses_data.get('data', {}).get('result', {}).get('expenses', [])
            summarized_data = summarize_expenses(expenses_list)
            
            # We return the summarized JSON string to the LLM.
            return json.dumps(summarized_data)
        except requests.exceptions.RequestException as e:
            logger.error(f"API call to {tool_name} failed: {e}")
            return json.dumps({"error": f"Failed to execute tool {tool_name}."})

    elif tool_name == "initiate_payment":
        logger.info(f"--- Starting Intelligent Payment Flow for: {parameters.get('recipient_name')} ---")
        recipient_name_query = parameters.get("recipient_name")
        if not recipient_name_query:
            return json.dumps({"error": "I need to know who you want to pay. Please provide a name."})

        # Step 1: Establish self-identity. Who am I?
        current_user = _get_current_user_identity()
        if not current_user:
            return json.dumps({"error": "I couldn't identify who you are, so I can't make a payment."})
        current_user_name = f"{current_user.get('first_name', '')} {current_user.get('last_name', '')}".strip()
        logger.info(f"Step 1: Identity confirmed as '{current_user_name}'.")

        # Step 2: Get all expenses for context.
        logger.info("Step 2: Fetching all expenses to calculate net balance.")
        expenses_url = f"{TOOLS_API_BASE_URL}/tools/getExpenses"
        expenses_headers = {'x-splitwise-key': f'{SPLITWISE_API_KEY}', 'Content-Type': 'application/json'}
        try:
            expenses_response = requests.post(expenses_url, headers=expenses_headers, data='{}')
            expenses_response.raise_for_status()
            all_expenses = expenses_response.json().get('data', {}).get('result', {}).get('expenses', [])
            logger.info(f"Successfully fetched {len(all_expenses)} expense records.")
        except requests.exceptions.RequestException as e:
            logger.error(f"Internal call to getExpenses failed: {e}")
            return json.dumps({"error": "I couldn't retrieve the list of expenses to find the payment details."})

        # Step 3: Calculate the net balance between the current user and the recipient.
        logger.info(f"Step 3: Calculating net balance between '{current_user_name}' and '{recipient_name_query}'.")
        net_balance = 0.0
        recipient_email = None
        recipient_full_name = None

        current_user_name_words = set(current_user_name.lower().split())
        recipient_query_words = set(recipient_name_query.lower().split())

        for expense in all_expenses:
            if expense.get('settled'):
                continue

            from_user_words = set(expense.get('from', '').lower().split())
            to_user_words = set(expense.get('to', '').lower().split())
            amount = float(expense.get('amount', 0.0))

            # Case 1: I (current user) owe them money.
            if current_user_name_words.issubset(from_user_words) and recipient_query_words.issubset(to_user_words):
                net_balance += amount
                if not recipient_email:
                    recipient_email = expense.get('to_email')
                    recipient_full_name = expense.get('to')

            # Case 2: They owe me money.
            elif recipient_query_words.issubset(from_user_words) and current_user_name_words.issubset(to_user_words):
                net_balance -= amount
        
        logger.info(f"Final calculated net balance is: {net_balance:.2f}")

        # Step 4: Act based on the calculated net balance.
        if net_balance <= 0:
            message = f"There is no outstanding balance for you to pay to {recipient_name_query}. "
            if net_balance < 0:
                message += f"In fact, they owe you {abs(net_balance):.2f}."
            else:
                message += "Your balance appears to be settled."
            return json.dumps({"error": message})

        if not recipient_email:
            return json.dumps({"error": f"I calculated that you owe {net_balance:.2f}, but I couldn't find an email for {recipient_name_query} to send the payment."})

        # Step 5: If a payment is needed, call the payment API with the exact payload.
        payment_payload = {
            "customer_email": recipient_email,
            "link_amount": int(net_balance * 100),
            "customer_name": recipient_full_name or recipient_name_query
        }
        
        logger.info(f"Step 4: Preparing to call payment API with exact payload: {payment_payload}")
        
        payment_url = f"{TOOLS_API_BASE_URL}/tools/createPaymentLink"
        payment_headers = {
            'Content-Type': 'application/json',
            'x-api-version': '2023-08-01',
            'x-client-id': CASHFREE_CLIENT_ID,
            'x-client-secret': CASHFREE_CLIENT_SECRET
        }

        try:
            payment_response = requests.post(payment_url, headers=payment_headers, json=payment_payload)
            payment_response.raise_for_status()
            payment_data = payment_response.json()
            logger.info(f"Payment link API call successful: {payment_data}")
            return json.dumps(payment_data)
        except requests.exceptions.RequestException as e:
            logger.error(f"Payment link creation failed: {e}")
            return json.dumps({"error": "I tried to create the payment link, but the request to the payment service failed."})
    else:
        logger.warning(f"LLM tried to call an unknown tool: {tool_name}")
        return json.dumps({"error": "Unknown tool."})

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
def get_llm_response(text: str, language_code: str = "en-IN"):
    """
    Manages the interaction with the LLM, including tool-calling logic.
    """
    if not sarvam_client:
        logger.error("SarvamAI client not available.")
        return "The AI model is currently unavailable. Please try again later."

    # 1. First Pass: Tool Selection
    # The system prompt now instructs the LLM on how to use tools.
    system_prompt_for_tool_selection = f"""
You are a smart financial assistant with access to expense tracking and payment tools. Analyze user queries carefully to determine if they require tool usage.

TOOL USAGE CRITERIA:
- User asks about expenses, bills, spending, or financial transactions → use "get_expenses"
- User asks about their identity, name, or account details → use "get_current_user"  
- User wants to pay someone, settle a debt, or send money → use "initiate_payment"

CONVERSATIONAL QUERIES (no tool needed):
- Greetings, thanks, small talk
- General questions unrelated to finances
- Clarifying questions about previous responses

RESPONSE FORMAT:
If tool is needed, respond ONLY with clean JSON (no markdown, no extra text):
{{
  "tool_name": "exact_tool_name",
  "parameters": {{"parameter_name": "value"}}
}}

If conversational, respond naturally in {language_code} language.

Available tools:
{json.dumps(TOOLS, indent=2)}

CRITICAL: For payment requests, extract the person's name accurately from the user's speech. Common variations like "John" vs "Jon" or "Mike" vs "Michael" should be handled consistently.
"""
    
    messages = [
        {"role": "system", "content": system_prompt_for_tool_selection},
        {"role": "user", "content": text}
    ]
    
    logger.info(f"Sending to LLM for tool selection: {text}")
    try:
        response = sarvam_client.chat.completions(
            messages=messages,
            max_tokens=550, # Increased tokens to allow for JSON response
            temperature=0.0, # Low temperature for reliable JSON output
        )
        llm_output = response.choices[0].message.content
        logger.info(f"Received from LLM (initial pass): {llm_output}")

        # 2. Check if the LLM wants to call a tool
        try:
            tool_call_request = json.loads(llm_output)
            tool_name = tool_call_request.get("tool_name")
            
            if tool_name:
                # 3. Execute the tool
                tool_result = call_tool(tool_name, tool_call_request.get("parameters", {}))
                
                # 4. Second Pass: Generate Final Response
                # Now we send the tool's result back to the LLM to generate a human-friendly response.
                system_prompt_for_final_response = f"""You are a professional financial assistant providing clear, actionable responses. Transform tool results into natural, conversational answers.

LANGUAGE: Respond in {language_code}. Translate any English data to {language_code}.

RESPONSE STYLE:
- Concise but complete (1-2 sentences max)
- Friendly and professional tone
- Direct and actionable
- No technical jargon or JSON terminology

FORMATTING REQUIREMENTS:
- Single paragraph, plain text only
- NO markdown, bullets, stars, or special formatting
- NO URLs or links in the response text
- Numbers should be clearly stated with currency when relevant

CONTENT GUIDELINES:

For EXPENSES queries:
- Focus on amounts the user owes or is owed
- Clearly identify who owes whom
- Provide specific amounts and currency
- If multiple transactions exist, give totals or key highlights
- Example: "You owe John 250 rupees from the dinner bill last week"

For USER IDENTITY queries:
- Provide name and key details naturally
- Example: "Your account is registered under John Smith with email john@email.com"

For PAYMENT requests:
- If successful: Confirm payment initiation and next steps
- If error: Explain the issue clearly and suggest solutions
- For payment links: Say "I've created a payment link" but don't include the actual URL
- Example: "I've set up a payment of 250 rupees to John. You'll receive the payment link shortly"

ERROR HANDLING:
- Convert technical errors to user-friendly explanations
- Provide clear next steps when possible
- Stay supportive and helpful
"""
                
                final_messages = [
                    {"role": "system", "content": system_prompt_for_final_response},
                    {"role": "user", "content": f"My original question was: '{text}'"},
                    {"role": "assistant", "content": f"I have run the tool '{tool_name}' and the result is: {tool_result}"},
                    {"role": "user", "content": "Now, please give me the final answer based on this information."}
                ]
                
                logger.info(f"Sending tool result to LLM for final response generation.")
                final_response = sarvam_client.chat.completions(
                    messages=final_messages,
                    max_tokens=300, # Increased from 100 to allow for a full, detailed response
                    temperature=0.7,
                )
                logger.info(f"Final response: {final_response}")
                final_content = final_response.choices[0].message.content
                logger.info(f"Received from LLM (final response): {final_content}")
                return final_content
            else:
                # If it's valid JSON but not a tool call, treat as conversational
                return llm_output

        except (json.JSONDecodeError, AttributeError):
            # If the output is not a JSON object, it's a direct conversational response.
            logger.info("LLM response is conversational, not a tool call.")
            return llm_output

    except Exception as e:
        logger.error(f"LLM request failed: {e}", exc_info=True)
        return "I'm sorry, I had trouble processing your request."

# --- SarvamAI Text-to-Speech (TTS) Function ---
def convert_text_to_speech(text: str, language_code: str = "en-IN"):
    """
    Converts text to speech using SarvamAI, correctly combines all audio chunks, 
    and returns a single, valid WAV audio byte string.
    """
    if not sarvam_client:
        logger.error("SarvamAI client not available.")
        return None
    
    logger.info(f"Sending to TTS: '{text}' in language: {language_code}")
    try:
        response = sarvam_client.text_to_speech.convert(
            text=text,
            target_language_code=language_code,
            speaker="anushka",
            model="bulbul:v2",
            speech_sample_rate=8000
        )
        
        audio_chunks_base64 = response.audios
        if not audio_chunks_base64:
            logger.error("TTS response contained no audio chunks.")
            return None

        logger.info(f"Received {len(audio_chunks_base64)} audio chunks from TTS. Combining them...")

        # Decode all chunks from base64 into a list of bytes
        decoded_chunks = [base64.b64decode(chunk) for chunk in audio_chunks_base64]

        # 1. Read the audio parameters from the first chunk.
        with wave.open(io.BytesIO(decoded_chunks[0]), 'rb') as wf:
            params = wf.getparams()

        # 2. Read the raw audio data (frames) from *all* chunks.
        all_frames = []
        for chunk_bytes in decoded_chunks:
            with wave.open(io.BytesIO(chunk_bytes), 'rb') as wf:
                all_frames.append(wf.readframes(wf.getnframes()))

        # 3. Create a new, final WAV file in memory.
        final_wav_buffer = io.BytesIO()
        with wave.open(final_wav_buffer, 'wb') as final_wf:
            # 4. Write the correct header and the combined audio data.
            final_wf.setparams(params)
            final_wf.writeframes(b"".join(all_frames))

        final_wav_bytes = final_wav_buffer.getvalue()
        logger.info("Successfully combined audio chunks into a single WAV file.")
        return final_wav_bytes

    except Exception as e:
        logger.error(f"TTS request or audio combination failed: {e}", exc_info=True)
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