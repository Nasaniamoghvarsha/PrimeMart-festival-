from flask import Blueprint, request, jsonify, session, redirect, url_for, flash, render_template, send_file
from marketplace.models import _orders, _products, _carts, get_user_orders, _as_object_id
from datetime import datetime
import uuid
import os
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib
from marketplace.config import Config

payment_bp = Blueprint('payment', __name__)

# Mock payment processor (replace with actual payment processor like Stripe in production)
def process_payment(amount, token, description):
    # In a real application, this would integrate with a payment processor
    # For now, we'll simulate a successful payment
    return {
        'success': True,
        'transaction_id': f'tx_{uuid.uuid4().hex[:16]}',
        'amount': amount,
        'currency': 'USD'
    }

def generate_pdf_receipt(order, user_email):
    """Generate a PDF receipt for the order"""
    # Create a PDF document
    receipt_id = f"RCPT-{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4())[:8].upper()}"
    filename = f"receipt_{receipt_id}.pdf"
    filepath = os.path.join('static', 'receipts', filename)
    
    # Create receipts directory if it doesn't exist
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    doc = SimpleDocTemplate(filepath, pagesize=letter)
    elements = []
    
    # Define styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'Title',
        parent=styles['Heading1'],
        fontSize=18,
        spaceAfter=20,
        alignment=1  # Center aligned
    )
    
    # Add title
    elements.append(Paragraph("Order Receipt", title_style))
    
    # Add order details
    elements.append(Paragraph(f"<b>Receipt #:</b> {receipt_id}", styles['Normal']))
    elements.append(Paragraph(f"<b>Date:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal']))
    elements.append(Paragraph(f"<b>Order #:</b> {order['_id']}", styles['Normal']))
    elements.append(Spacer(1, 20))
    
    # Add items table
    data = [['Item', 'Price', 'Quantity', 'Total']]
    for item in order['items']:
        data.append([
            item['name'],
            f"${item['price']:.2f}",
            item['quantity'],
            f"${item['price'] * item['quantity']:.2f}"
        ])
    
    # Add total
    total = sum(item['price'] * item['quantity'] for item in order['items'])
    data.append(['', '', 'Subtotal:', f"${total:.2f}"])
    data.append(['', '', 'Tax (10%):', f"${total * 0.1:.2f}"])
    data.append(['', '', 'Total:', f"${total * 1.1:.2f}"])
    
    # Create table
    table = Table(data, colWidths=[250, 80, 80, 80])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),  # Left align item names
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    
    elements.append(table)
    elements.append(Spacer(1, 20))
    elements.append(Paragraph("Thank you for your order!", styles['Normal']))
    
    # Build PDF
    doc.build(elements)
    
    return filename, receipt_id

def send_email_with_receipt(recipient_email, order, receipt_path):
    """Send an email with the receipt attached"""
    try:
        # Create message
        msg = MIMEMultipart()
        msg['From'] = Config.MAIL_DEFAULT_SENDER
        msg['To'] = recipient_email
        msg['Subject'] = f"Your Order Receipt #{order['_id']}"
        
        # Email body
        body = f"""
        <h2>Thank you for your order!</h2>
        <p>Your order #{order['_id']} has been received and is being processed.</p>
        <p>You can find your receipt attached to this email.</p>
        <p>Order Summary:</p>
        <ul>
        """
        
        for item in order['items']:
            body += f"<li>{item['name']} x {item['quantity']} - ${item['price'] * item['quantity']:.2f}</li>"
        
        total = sum(item['price'] * item['quantity'] for item in order['items']) * 1.1  # Including 10% tax
        body += f"</ul><p><strong>Total: ${total:.2f} (including tax)</strong></p>"
        body += "<p>If you have any questions, please contact our support team.</p>"
        
        msg.attach(MIMEText(body, 'html'))
        
        # Attach receipt
        with open(receipt_path, 'rb') as f:
            attachment = MIMEText(f.read(), 'base64', 'utf-8')
            attachment.add_header('Content-Disposition', 'attachment', filename=os.path.basename(receipt_path))
            msg.attach(attachment)
        
        # Send email (in production, use a proper email service)
        with smtplib.SMTP(Config.MAIL_SERVER, Config.MAIL_PORT) as server:
            if Config.MAIL_USE_TLS:
                server.starttls()
            if Config.MAIL_USERNAME and Config.MAIL_PASSWORD:
                server.login(Config.MAIL_USERNAME, Config.MAIL_PASSWORD)
            server.send_message(msg)
            
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        return False

@payment_bp.route('/checkout', methods=['GET', 'POST'])
def checkout():
    print("\n=== DEBUG: Starting checkout process ===")
    if 'user' not in session:
        print("DEBUG: No user in session, redirecting to login")
        flash('Please login to proceed to checkout.', 'warning')
        return redirect(url_for('auth_bp.login'))
    
    # Get user ID from session
    user = session.get('user')
    user_id = user.get('_id') or user.get('id')
    print(f"DEBUG: Session user data: {user}")
    print(f"DEBUG: Extracted user_id: {user_id}, Type: {type(user_id)}")
    
    if not user_id:
        print("DEBUG: No user_id found in session")
        flash('User session error. Please login again.', 'error')
        return redirect(url_for('auth_bp.login'))
    
    # Get the cart directly from the database
    from pymongo import MongoClient
    from bson import ObjectId
    
    client = MongoClient('mongodb://localhost:27017')
    db = client['marketplace']
    
    # Try to find the cart with the user_id as string (which is what we have in the session)
    cart = db.carts.find_one({'user_id': user_id})
    print(f"DEBUG: Cart from database (string user_id): {cart}")
    
    # If not found, try with ObjectId
    if not cart and ObjectId.is_valid(user_id):
        cart = db.carts.find_one({'user_id': ObjectId(user_id)})
        print(f"DEBUG: Cart from database (ObjectId user_id): {cart}")
    
    if not cart:
        print("DEBUG: No cart found for user, creating a new one")
        cart = {'items': []}
    
    if 'items' not in cart:
        cart['items'] = []
    
    print(f"DEBUG: Cart items count: {len(cart.get('items', []))}")
    print(f"DEBUG: Cart items: {cart.get('items')}")
    
    if not cart.get('items'):
        print("DEBUG: Cart is empty, redirecting to store")
        flash('Your cart is empty!', 'warning')
        return redirect(url_for('product_bp.store'))
    
    # Get product details for items in cart
    from bson import ObjectId
    print("\n=== DEBUG: Cart Items Before Processing ===")
    for i, item in enumerate(cart['items'], 1):
        print(f"Item {i}: {item}")
    
    # Convert string product_ids to ObjectId for querying
    try:
        product_ids = [ObjectId(item['product_id']) for item in cart['items']]
        print(f"\n=== DEBUG: Converted Product IDs ===")
        print(f"Product IDs: {product_ids}")
        
        products = list(_products.find({'_id': {'$in': product_ids}}))
        print(f"\n=== DEBUG: Products Found in Database ===")
        print(f"Found {len(products)} products in database")
        for i, p in enumerate(products, 1):
            print(f"Product {i}: ID={p['_id']}, Name={p.get('name', 'N/A')}, Price={p.get('price', 'N/A')}")
    except Exception as e:
        print(f"\n=== DEBUG: Error processing products ===")
        print(f"Error: {str(e)}")
        print(f"Type: {type(e).__name__}")
        products = []
    
    # Map product details to cart items
    cart_items = []
    total = 0
    print("\n=== DEBUG: Mapping Products to Cart Items ===")
    
    for item in cart['items']:
        print(f"\nProcessing cart item: {item}")
        product = next((p for p in products if str(p['_id']) == item['product_id']), None)
        
        if product:
            qty = item.get('qty', 1)
            item_total = product['price'] * qty
            total += item_total
            cart_item = {
                'product_id': str(product['_id']),
                'name': product.get('name', 'Unknown Product'),
                'price': product.get('price', 0),
                'quantity': qty,
                'total': item_total,
                'image_url': product.get('image_url', '')
            }
            cart_items.append(cart_item)
            print(f"Added to cart items: {cart_item}")
        else:
            print(f"Product not found for ID: {item.get('product_id')}")
    
    print(f"\n=== DEBUG: Final Cart Items ===")
    print(f"Total cart items: {len(cart_items)}")
    for i, item in enumerate(cart_items, 1):
        print(f"Cart Item {i}: {item}")
    
    # Add tax (10% for example)
    tax = total * 0.1
    grand_total = total + tax
    
    # Debug information
    print(f"DEBUG: Cart items before rendering template: {cart_items}")
    print(f"DEBUG: Cart items count: {len(cart_items)}")
    print(f"DEBUG: Subtotal: {total}, Tax: {tax}, Grand Total: {grand_total}")
    
    if request.method == 'GET':
        return render_template('checkout.html', 
                            cart_items=cart_items,
                            subtotal=total,
                            tax=tax,
                            grand_total=grand_total,
                            user=session.get('user'))
    
    # Handle POST request
    if request.method == 'POST':
        # Process payment
        payment_token = request.form.get('payment_token')
        email = request.form.get('email', session['user'].get('email', ''))
        
        # In a real app, validate the payment token with your payment processor
        payment_result = process_payment(grand_total, payment_token, f"Order from {email}")
        
        if payment_result.get('success'):
            # Create order
            order = {
                'user_id': user_id,
                'email': email,
                'items': cart_items,
                'subtotal': total,
                'tax': tax,
                'total': grand_total,
                'status': 'completed',
                'payment_id': payment_result['transaction_id'],
                'created_at': datetime.utcnow(),
                'updated_at': datetime.utcnow()
            }
            
            # Save order to database
            result = _orders.insert_one(order)
            order_id = str(result.inserted_id)
            
            # Generate receipt
            receipt_filename, receipt_id = generate_pdf_receipt({
                '_id': order_id,
                'items': cart_items,
                'subtotal': total,
                'tax': tax,
                'total': grand_total,
                'created_at': datetime.utcnow()
            }, email)
            
            # Update order with receipt info
            _orders.update_one(
                {'_id': result.inserted_id},
                {'$set': {
                    'receipt_id': receipt_id,
                    'receipt_path': f'/static/receipts/{receipt_filename}'
                }}
            )
            
            # Clear cart
            _carts.update_one(
                {'user_id': user_id},
                {'$set': {'items': [], 'updated_at': datetime.utcnow()}},
                upsert=True
            )
            
            # Send email with receipt
            send_email_with_receipt(
                email,
                order,
                os.path.join('static', 'receipts', receipt_filename)
            )
            
            flash('Order placed successfully! A receipt has been sent to your email.', 'success')
            return redirect(url_for('payment.order_confirmation', order_id=order_id))
        else:
            flash('Payment failed. Please try again or contact support.', 'danger')
    
    return render_template('checkout.html', 
                         cart_items=cart_items, 
                         subtotal=total, 
                         tax=tax, 
                         grand_total=grand_total,
                         user=session['user'])

@payment_bp.route('/order/confirmation/<order_id>')
def order_confirmation(order_id):
    if 'user' not in session:
        flash('Please login to view this page.', 'warning')
        return redirect(url_for('auth_bp.login'))
    
    order = _orders.find_one({'_id': order_id, 'user_id': session['user'].get('_id')})
    if not order:
        flash('Order not found.', 'danger')
        return redirect(url_for('product_bp.store'))
    
    return render_template('order_confirmation.html', order=order)

@payment_bp.route('/receipt/<order_id>')
def view_receipt(order_id):
    if 'user' not in session:
        return jsonify({'status': 'error', 'message': 'Please login to view this page'}), 401
    
    try:
        from bson import ObjectId
        order_id = ObjectId(order_id)
    except:
        return jsonify({'status': 'error', 'message': 'Invalid order ID'}), 400
    
    order = _orders.find_one({'_id': order_id, 'user_id': session['user'].get('_id')})
    if not order:
        return jsonify({'status': 'error', 'message': 'Receipt not found'}), 404
    
    try:
        # Generate PDF receipt
        user_email = session['user'].get('email', '')
        pdf_path = generate_pdf_receipt(order, user_email)
        
        if not os.path.exists(pdf_path):
            return jsonify({'status': 'error', 'message': 'Failed to generate receipt'}), 500
        
        # Send the file for download
        return send_file(
            pdf_path,
            as_attachment=True,
            download_name=f'receipt-{order_id}.pdf',
            mimetype='application/pdf'
        )
    except Exception as e:
        print(f"Error generating receipt: {str(e)}")
        return jsonify({'status': 'error', 'message': 'Failed to generate receipt'}), 500

@payment_bp.route('/orders')
def my_orders():
    if 'user' not in session:
        flash('Please login to view your orders.', 'warning')
        return redirect(url_for('auth_bp.login'))
    
    orders = list(_orders.find(
        {'user_id': session['user'].get('_id')},
        sort=[('created_at', -1)]
    ))
    
    return render_template('my_orders.html', orders=orders)
