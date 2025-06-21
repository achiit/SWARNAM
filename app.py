
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import json
import re
import os
import requests
from datetime import datetime

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Sarvam AI Configuration
SARVAM_API_KEY = os.getenv('SARVAM_API_KEY', 'your-sarvam-api-key-here')
SARVAM_BASE_URL = 'https://api.sarvam.ai/v1'

# Sample contacts database
CONTACTS = {
    "sandeep": {"name": "Sandeep", "upi_id": "sandeep@paytm", "phone": "9999999999"},
    "priya": {"name": "Priya", "upi_id": "priya@gpay", "phone": "8888888888"},
    "rahul": {"name": "Rahul", "upi_id": "rahul@phonepe", "phone": "7777777777"}
}

# Transaction log
TRANSACTIONS = []

class VoicePaymentProcessor:
    def __init__(self):
        self.amount_patterns = [
            r'(\d+)\s*(?:rupees?|rs\.?|₹)',
            r'(?:rupees?|rs\.?|₹)\s*(\d+)',
            r'(\d+)',
            r'(one hundred|two hundred|three hundred|four hundred|five hundred|thousand)',
        ]
        
        self.payment_patterns = [
            r'(?:send|pay|transfer|give)\s+(?:rupees?\s*)?(\d+|one hundred|two hundred|three hundred|four hundred|five hundred|thousand)(?:\s*rupees?)?\s+(?:to\s+)?(\w+)',
            r'(?:send|pay|transfer|give)\s+(\w+)\s+(?:rupees?\s*)?(\d+|one hundred|two hundred|three hundred|four hundred|five hundred|thousand)(?:\s*rupees?)?',
            r'pay\s+(\w+)\s+(?:rupees?\s*)?(\d+|one hundred|two hundred|three hundred|four hundred|five hundred|thousand)(?:\s*rupees?)?\s+for\s+(.*)',
        ]
    
    def enhance_with_sarvam_ai(self, text):
        """Use Sarvam AI for better text understanding"""
        try:
            headers = {
                'Authorization': f'Bearer {SARVAM_API_KEY}',
                'Content-Type': 'application/json'
            }
            
            payload = {
                'model': 'sarvam-1',
                'messages': [
                    {
                        'role': 'system',
                        'content': 'You are a payment intent classifier. Extract amount, recipient name, and reason from payment commands. Respond in JSON format with fields: amount (number), recipient (string), reason (string or null).'
                    },
                    {
                        'role': 'user',
                        'content': f'Extract payment details from: "{text}"'
                    }
                ],
                'max_tokens': 100,
                'temperature': 0.1
            }
            
            response = requests.post(
                f'{SARVAM_BASE_URL}/chat/completions',
                headers=headers,
                json=payload,
                timeout=10
            )
            
            if response.status_code == 200:
                result = response.json()
                ai_response = result['choices'][0]['message']['content']
                try:
                    return json.loads(ai_response)
                except json.JSONDecodeError:
                    pass
        except Exception as e:
            print(f"Sarvam AI error: {e}")
        
        return None
    
    def extract_amount(self, text):
        """Extract amount from text"""
        text = text.lower()
        
        # Word to number mapping
        word_to_num = {
            'one hundred': 100, 'hundred': 100,
            'two hundred': 200, 'three hundred': 300,
            'four hundred': 400, 'five hundred': 500,
            'thousand': 1000, 'one thousand': 1000
        }
        
        for pattern in self.amount_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                amount_str = match.group(1)
                if amount_str in word_to_num:
                    return word_to_num[amount_str]
                elif amount_str.isdigit():
                    return int(amount_str)
        return None
    
    def extract_contact(self, text):
        """Extract contact name from text"""
        text = text.lower()
        for contact_key, contact_info in CONTACTS.items():
            if contact_key in text or contact_info['name'].lower() in text:
                return contact_info
        return None
    
    def process_voice_command(self, text):
        """Process voice command and extract payment intent"""
        original_text = text
        text = text.lower().strip()
        
        # First try Sarvam AI for better understanding
        ai_result = self.enhance_with_sarvam_ai(original_text)
        if ai_result:
            amount = ai_result.get('amount')
            recipient_name = ai_result.get('recipient')
            reason = ai_result.get('reason')
            
            # Find contact by name
            contact = None
            if recipient_name:
                for contact_key, contact_info in CONTACTS.items():
                    if (contact_key.lower() == recipient_name.lower() or 
                        contact_info['name'].lower() == recipient_name.lower()):
                        contact = contact_info
                        break
            
            if amount and contact:
                return {
                    'success': True,
                    'amount': amount,
                    'contact': contact,
                    'reason': reason,
                    'message': f"Confirming payment of {amount} rupees to {contact['name']}" + 
                              (f" for {reason}" if reason else "") + ". Say 'confirm' to proceed."
                }
        
        # Fallback to original pattern matching
        amount = self.extract_amount(text)
        contact = self.extract_contact(text)
        
        # Extract reason (optional)
        reason_match = re.search(r'for\s+(.*)', text)
        reason = reason_match.group(1) if reason_match else None
        
        if amount and contact:
            return {
                'success': True,
                'amount': amount,
                'contact': contact,
                'reason': reason,
                'message': f"Confirming payment of {amount} rupees to {contact['name']}" + 
                          (f" for {reason}" if reason else "") + ". Say 'confirm' to proceed."
            }
        elif contact and not amount:
            return {
                'success': False,
                'error': f"How much do you want to send to {contact['name']}?",
                'contact': contact
            }
        elif amount and not contact:
            return {
                'success': False,
                'error': "Who do you want to send the money to?",
                'amount': amount
            }
        else:
            return {
                'success': False,
                'error': "I didn't understand. Try saying 'send 100 rupees to Sandeep'"
            }

processor = VoicePaymentProcessor()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/process_voice', methods=['POST'])
def process_voice():
    data = request.get_json()
    text = data.get('text', '')
    
    # Process confirmation
    if text.lower() in ['confirm', 'yes', 'proceed', 'ok']:
        # Get the last pending transaction from session (simplified)
        # In real app, you'd use proper session management
        return jsonify({
            'success': True,
            'message': 'Payment successful!',
            'action': 'payment_complete'
        })
    
    # Process payment command
    result = processor.process_voice_command(text)
    return jsonify(result)

@app.route('/execute_payment', methods=['POST'])
def execute_payment():
    data = request.get_json()
    
    # Simulate payment processing
    transaction = {
        'id': len(TRANSACTIONS) + 1,
        'amount': data.get('amount'),
        'contact': data.get('contact'),
        'reason': data.get('reason'),
        'timestamp': datetime.now().isoformat(),
        'status': 'success'
    }
    
    TRANSACTIONS.append(transaction)
    
    return jsonify({
        'success': True,
        'message': f"Payment of {transaction['amount']} rupees to {transaction['contact']['name']} successful!",
        'transaction_id': transaction['id']
    })

@app.route('/contacts')
def get_contacts():
    return jsonify(list(CONTACTS.values()))

@app.route('/transactions')
def get_transactions():
    return jsonify(TRANSACTIONS)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
