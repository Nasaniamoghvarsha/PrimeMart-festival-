from io import BytesIO
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle
from reportlab.lib.units import inch, cm
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from datetime import datetime
import os

def generate_receipt_pdf(order_data, logo_path=None, output_path=None):
    """
    Generate a PDF receipt for an order.
    
    Args:
        order_data (dict): Order data including items, total, etc.
        logo_path (str, optional): Path to the logo image file.
        output_path (str, optional): Path to save the PDF. If None, returns PDF as bytes.
    
    Returns:
        bytes or None: PDF content if output_path is None, otherwise None
    """
    # Create a file-like buffer to receive PDF data
    buffer = BytesIO()
    
    # Create the PDF object, using the buffer as its "file."
    doc = SimpleDocTemplate(
        buffer if output_path is None else output_path,
        pagesize=A4,
        rightMargin=72, leftMargin=72,
        topMargin=72, bottomMargin=72
    )
    
    # Container for the 'Flowable' objects
    elements = []
    
    # Define custom styles
    styles = getSampleStyleSheet()
    
    # Add title style
    styles.add(ParagraphStyle(
        name='Title',
        parent=styles['Heading1'],
        fontSize=24,
        alignment=TA_CENTER,
        spaceAfter=30,
        textColor=colors.HexColor('#8B0000')  # Dark red color
    ))
    
    # Add subtitle style
    styles.add(ParagraphStyle(
        name='Subtitle',
        parent=styles['Normal'],
        fontSize=12,
        alignment=TA_CENTER,
        spaceAfter=20
    ))
    
    # Add header style
    styles.add(ParagraphStyle(
        name='Header',
        parent=styles['Heading2'],
        fontSize=14,
        spaceAfter=10,
        textColor=colors.HexColor('#333333')
    ))
    
    # Add normal text style
    styles.add(ParagraphStyle(
        name='NormalText',
        parent=styles['Normal'],
        fontSize=10,
        leading=14
    ))
    
    # Add footer style
    styles.add(ParagraphStyle(
        name='Footer',
        parent=styles['Normal'],
        fontSize=8,
        alignment=TA_CENTER,
        spaceBefore=20,
        textColor=colors.gray
    ))
    
    # Add logo if provided
    if logo_path and os.path.exists(logo_path):
        try:
            logo = Image(logo_path, width=2*inch, height=1*inch)
            logo.hAlign = 'CENTER'
            elements.append(logo)
            elements.append(Spacer(1, 20))
        except Exception as e:
            print(f"Error loading logo: {e}")
    
    # Add title
    elements.append(Paragraph("PRIMEMART", styles['Title']))
    elements.append(Paragraph("INVOICE / RECEIPT", styles['Subtitle']))
    
    # Add order info
    elements.append(Paragraph(f"Order #: {order_data.get('order_number', 'N/A')}", styles['NormalText']))
    elements.append(Paragraph(f"Date: {order_data.get('order_date', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}", styles['NormalText']))
    elements.append(Spacer(1, 20))
    
    # Add customer info
    elements.append(Paragraph("Bill To:", styles['Header']))
    elements.append(Paragraph(order_data.get('customer_name', 'Customer'), styles['NormalText']))
    elements.append(Paragraph(order_data.get('delivery_address', 'N/A'), styles['NormalText']))
    elements.append(Spacer(1, 20))
    
    # Create table for order items
    data = [['Item', 'Price', 'Qty', 'Total']]  # Header row
    
    # Add order items
    for item in order_data.get('items', []):
        data.append([
            item.get('name', 'Product'),
            f"${float(item.get('price', 0)):.2f}",
            str(item.get('qty', 1)),
            f"${float(item.get('price', 0)) * int(item.get('qty', 1)):.2f}"
        ])
    
    # Add total row
    data.append(['', '', 'Subtotal:', f"${order_data.get('subtotal', 0):.2f}"])
    data.append(['', '', 'Tax (0%):', '$0.00'])  # You can add tax calculation if needed
    data.append(['', '', 'Total:', f"${order_data.get('total', 0):.2f}"])
    
    # Create table
    table = Table(data, colWidths=[200, 80, 80, 80])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#8B0000')),  # Header background
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),  # Header text color
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),  # Center align all cells
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),  # Left align first column
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),  # Header font
        ('FONTSIZE', (0, 0), (-1, 0), 10),  # Header font size
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),  # Header padding
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),  # Table body background
        ('GRID', (0, 0), (-1, -4), 1, colors.lightgrey),  # Grid for items
        ('LINEABOVE', (2, -3), (-1, -1), 1, colors.black),  # Line above total
        ('LINEBELOW', (0, -1), (-1, -1), 1, colors.black),  # Line below total
        ('FONTNAME', (0, -3), (-1, -1), 'Helvetica-Bold'),  # Make total row bold
    ]))
    
    elements.append(table)
    elements.append(Spacer(1, 20))
    
    # Add thank you message
    elements.append(Paragraph("Thank you for shopping with PRIMEMART!", styles['NormalText']))
    elements.append(Spacer(1, 10))
    elements.append(Paragraph("For any inquiries, please contact support@primemart.com", styles['NormalText']))
    
    # Add footer
    elements.append(Spacer(1, 40))
    elements.append(Paragraph("PRIMEMART - Your Trusted Shopping Destination", styles['Footer']))
    elements.append(Paragraph("123 Market St, City, Country | Phone: +1 234 567 8900", styles['Footer']))
    elements.append(Paragraph("www.primemart.com | support@primemart.com", styles['Footer']))
    
    # Build the PDF
    doc.build(elements)
    
    # File is created, get the value and return it
    if output_path is None:
        buffer.seek(0)
        return buffer.getvalue()
    return None

def save_receipt_to_file(order_data, output_path, logo_path=None):
    """Generate and save a PDF receipt to the specified path."""
    return generate_receipt_pdf(order_data, logo_path=logo_path, output_path=output_path)

def get_receipt_as_bytes(order_data, logo_path=None):
    """Generate and return a PDF receipt as bytes."""
    return generate_receipt_pdf(order_data, logo_path=logo_path)
