# Bhindi Voice Payment Agent - AI-Powered Voice Assistant

![Project Overview](twilio_voice_assistant/Blue%20Minimalist%20Project%20Flowchart.png)

A sophisticated voice-first payment agent that demonstrates intent-driven transaction processing through natural language understanding. This project integrates Twilio's voice capabilities with SarvamAI for speech processing and intelligent conversation handling.

## 🎯 Project Vision

Create a voice assistant that understands payment intents beyond simple commands, enabling natural language transactions like *"Pay Sandeep for last night's dinner"* instead of rigid *"Send 100rs to Sandeep."* The system provides a hands-free, conversational approach to financial transactions with advanced context understanding.

## 🏗️ Architecture Overview

### Voice Processing Flow

![Voice Assistant Flow](twilio_voice_assistant/Beautiful%20Diagram%20Jun%2022%202025.png)

The voice assistant follows a sophisticated bidirectional audio streaming architecture:

1. **Twilio Call Initiation** → **WebSocket Connection**
2. **Audio Buffer (μ-law chunks)** → **Buffer Threshold (24K bytes = 3 sec)**
3. **μ-law → WAV Conversion** → **WAV → μ-law Conversion**
4. **SarvamAI STT (Speech-to-Text)** → **LLM Processing**
5. **Tool Decision Logic** → **Direct Response** (if no tools needed)
6. **SarvamAI TTS (Text-to-Speech)** → **Base64 Encode**
7. **WebSocket Send** → **Twilio Playback**

### Technical Stack

#### Backend Infrastructure
- **FastAPI**: High-performance web framework for API endpoints
- **WebSockets**: Real-time bidirectional communication with Twilio
- **Twilio Voice API**: Telephony infrastructure and call handling
- **SarvamAI**: Advanced speech-to-text and text-to-speech processing
- **Python 3.12**: Core runtime environment

#### Key Dependencies
```
fastapi              # Web framework
uvicorn[standard]    # ASGI server
twilio              # Twilio SDK
sarvamai            # SarvamAI integration
websockets          # WebSocket support
python-dotenv       # Environment management
audioop-lts         # Audio processing
pywav               # WAV file handling
requests            # HTTP client
```

## 🚀 Features

### Core Capabilities

#### 🎤 Voice Processing
- **Real-time Audio Streaming**: Bidirectional WebSocket connection with Twilio
- **Advanced Audio Handling**: μ-law to WAV conversion and vice versa
- **Buffer Management**: Smart audio buffering (3-second windows for optimal processing)
- **Multi-language Support**: Dynamic language detection and processing

#### 🧠 Intelligent Conversation
- **Natural Language Understanding**: Context-aware payment intent recognition
- **LLM Integration**: Advanced conversational AI for complex queries
- **Tool Integration**: Automated decision-making for when to use external tools
- **Multi-turn Conversations**: Maintains context across conversation turns

#### 💳 Payment Processing
- **Contact Management**: Smart contact lookup and UPI ID resolution
- **Payment Intent Extraction**: Understands amounts, recipients, and reasons
- **Secure Confirmation Flow**: Voice-based payment confirmation
- **Transaction Logging**: Comprehensive audit trail

#### 🔧 Tool Integration
- **Expense Management**: Splitwise integration for bill splitting
- **Payment Gateway**: Cashfree integration for transaction processing
- **Dynamic Tool Calling**: Context-aware tool selection and execution

### Advanced Features

#### Audio Processing Pipeline
```python
# Audio flow: Twilio μ-law → WAV → Processing → WAV → μ-law → Twilio
def convert_mulaw_to_wav_bytes(mulaw_bytes: bytes) -> bytes
def convert_wav_to_mulaw_bytes(wav_bytes: bytes) -> bytes
```

#### Intelligent Buffering
- **24K bytes threshold** (approximately 3 seconds of audio)
- **Real-time processing** without blocking the audio stream
- **Buffer overflow protection** with smart clearing mechanisms

#### Comprehensive Logging
- **Incoming Audio Logs**: Raw audio streams from users
- **Outgoing Audio Logs**: Generated TTS responses
- **Processing Logs**: Detailed conversation flow tracking
- **Transaction Logs**: Complete payment processing history

## 📋 Supported Voice Commands

### Payment Commands
```
"Send 500 rupees to Sandeep"
"Pay Priya 200 for dinner"
"Transfer 1000 to Rahul for rent"
"Give Sandeep hundred rupees"
```

### Amount Recognition
- **Numbers**: 100, 500, 1000, 50
- **Words**: "hundred", "thousand", "fifty"
- **Currency**: "rupees", "rs", "₹"

### Contact Patterns
- **Exact name matching** from contact database
- **Case insensitive** matching
- **Nickname support** through contact aliases

## 🛠️ Installation & Setup

### Prerequisites
```bash
Python 3.12+
pip or poetry package manager
Twilio account with voice capabilities
SarvamAI API key
ngrok for local development tunneling
```

### Environment Configuration
Create a `.env` file in the project root:
```env
SARVAM_API_KEY=your_sarvam_api_key_here
TWILIO_ACCOUNT_SID=your_twilio_account_sid
TWILIO_AUTH_TOKEN=your_twilio_auth_token
TOOLS_API_BASE_URL=your_tools_api_base_url
SPLITWISE_API_KEY=your_splitwise_api_key
CASHFREE_CLIENT_ID=your_cashfree_client_id
CASHFREE_CLIENT_SECRET=your_cashfree_client_secret
```

### Installation Steps

#### Using Poetry (Recommended)
```bash
# Clone the repository
git clone <repository-url>
cd DelightfulEvenVolume

# Install dependencies
poetry install

# Activate virtual environment
poetry shell

# Run the main application
cd twilio_voice_assistant
python main.py
```

#### Using pip
```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
cd twilio_voice_assistant
pip install -r requirements.txt

# Run the application
python main.py
```

### Local Development Setup

1. **Start the FastAPI server**:
   ```bash
   cd twilio_voice_assistant
   uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```

2. **Expose local server using ngrok**:
   ```bash
   ngrok http 8000
   ```

3. **Configure Twilio webhook**:
   - Update the WebSocket URL in `main.py` with your ngrok URL
   - Set Twilio webhook to `https://your-ngrok-url.ngrok.io/incoming_call`

4. **Test the system**:
   - Call your Twilio phone number
   - Speak naturally to test voice processing

## 🔧 API Endpoints

### Core Endpoints

#### `/incoming_call` (POST)
Handles incoming Twilio voice calls and returns TwiML response to establish WebSocket connection.

**Response**: XML TwiML with WebSocket stream configuration

#### `/ws` (WebSocket)
Bidirectional audio streaming endpoint for real-time voice processing.

**Events**:
- `start`: Stream initialization
- `media`: Audio data chunks
- `stop`: Stream termination

### Alternative Interfaces

#### Flask Web Interface (`app.py`)
- **`/`**: Web-based voice interface
- **`/process_voice`**: Voice command processing
- **`/execute_payment`**: Payment execution
- **`/contacts`**: Contact management
- **`/transactions`**: Transaction history

## 📊 Data Models

### Contact Structure
```json
{
  "sandeep": {
    "name": "Sandeep",
    "upi_id": "sandeep@paytm",
    "phone": "9999999999"
  }
}
```

### Transaction Log
```json
{
  "timestamp": "2025-01-22T10:30:00Z",
  "amount": 500,
  "recipient": "Sandeep",
  "reason": "dinner",
  "status": "completed",
  "transaction_id": "txn_123456789"
}
```

### Audio Processing Logs
- **Incoming**: `audio_logs/input_{timestamp}.wav`
- **Outgoing**: `outgoing_audio_logs/tts_output_{timestamp}.wav`
- **Twilio Stream**: `outgoing_audio_logs/twilio_stream_{timestamp}.ulaw`

## 🔒 Security Features

### Voice Authentication
- **Caller ID verification** through Twilio
- **Voice confirmation** for all payment transactions
- **Session management** with stream ID tracking

### Payment Security
- **Two-step confirmation** process
- **Amount limits** and validation
- **Transaction logging** for audit trails
- **Test mode** for development safety

### Data Protection
- **Environment variable** security for API keys
- **Encrypted communication** through HTTPS/WSS
- **No permanent storage** of sensitive audio data

## 🧪 Testing

### Manual Testing
1. **Voice Commands**: Test various payment intents
2. **Error Handling**: Invalid amounts, unknown contacts
3. **Audio Quality**: Different network conditions
4. **Multi-language**: Various language inputs

### Automated Testing
```bash
# Run unit tests
python -m pytest tests/

# Test audio processing
python tests/test_audio_processing.py

# Test payment flows
python tests/test_payment_processing.py
```

## 📈 Performance Metrics

### Response Times
- **Voice Processing**: < 3 seconds
- **Intent Recognition**: < 1 second
- **Payment Execution**: < 5 seconds
- **Audio Conversion**: < 0.5 seconds

### Accuracy Targets
- **Speech Recognition**: > 95%
- **Intent Classification**: > 90%
- **Payment Success Rate**: > 99%
- **Audio Quality**: > 90% clarity

## 🚨 Troubleshooting

### Common Issues

#### WebSocket Connection Failed
```bash
# Check ngrok tunnel
ngrok http 8000

# Verify Twilio webhook configuration
# Ensure URL format: wss://your-domain.ngrok.io/ws
```

#### Audio Processing Errors
```bash
# Check audio dependencies
pip install audioop-lts pywav

# Verify SarvamAI credentials
# Test API connectivity
```

#### Payment Processing Issues
```bash
# Verify environment variables
# Check Cashfree/Splitwise API status
# Review transaction logs
```

## 🔮 Future Enhancements

### Planned Features
- **Multi-language Support**: Hindi, Tamil, Bengali voice processing
- **Advanced Context**: Calendar integration, expense categorization
- **Voice Biometrics**: Speaker identification and authentication
- **Mobile App**: Native iOS/Android applications
- **Advanced AI**: Custom NLP models for better intent recognition

### Technical Improvements
- **WebRTC Integration**: Direct browser-to-browser audio streaming
- **Edge Computing**: Reduced latency with edge deployment
- **Advanced Analytics**: Conversation analytics and insights
- **Blockchain Integration**: Decentralized payment processing

## 📚 Documentation

### Architecture Documents
- **API Documentation**: OpenAPI/Swagger specs available at `/docs`
- **Audio Processing**: Detailed technical documentation in `/docs/audio`
- **Payment Integration**: Integration guides in `/docs/payments`

### Development Guides
- **Contributing Guidelines**: See `CONTRIBUTING.md`
- **Deployment Guide**: See `DEPLOYMENT.md`
- **Security Guidelines**: See `SECURITY.md`

## 🤝 Contributing

We welcome contributions! Please read our contributing guidelines and submit pull requests for any improvements.

### Development Workflow
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## 📝 License

This project is licensed under the MIT License - see the `LICENSE` file for details.

## 🙏 Acknowledgments

- **Twilio**: Voice infrastructure and WebSocket streaming
- **SarvamAI**: Advanced speech processing capabilities
- **FastAPI**: High-performance web framework
- **Python Community**: Excellent audio processing libraries

---

**Built with ❤️ for the future of voice-first financial interactions**
