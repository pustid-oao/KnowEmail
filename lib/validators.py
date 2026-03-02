import re
import dns.resolver
import smtplib
import socket
from cachetools import TTLCache

# Cache for MX records
cache = TTLCache(maxsize=100, ttl=600)

def is_valid_email_syntax(email):
    regex = r'^\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    return re.match(regex, email) is not None

def has_mx_record(domain):
    try:
        resolver = dns.resolver.Resolver()
        resolver.lifetime = 5.0
        mx_records = resolver.resolve(domain, 'MX')
        return bool(mx_records)
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.resolver.LifetimeTimeout):
        return False

def verify_email_smtp(email):
    domain = email.split('@')[1]
    smtp_message = ""
    
    # Try custom DNS servers first, then fallback to system DNS
    dns_servers = ['8.8.8.8', '1.1.1.1']
    
    def try_resolve(dns_servers_list):
        resolver = dns.resolver.Resolver()
        resolver.nameservers = dns_servers_list
        resolver.lifetime = 5.0
        return resolver.resolve(domain, 'MX')
    
    try:
        # Try with custom DNS servers first
        try:
            mx_records = try_resolve(dns_servers)
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.resolver.LifetimeTimeout):
            # Fallback to system DNS
            mx_records = try_resolve([])
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.resolver.LifetimeTimeout) as e:
        smtp_message = f"DNS resolution failed: {str(e)}"
        return False, smtp_message

    if not mx_records:
        smtp_message = "No MX records found"
        return False, smtp_message

    # Try ports in order of preference: 25 (most likely to work), 587, 465
    smtp_ports = [25, 587, 465]
    timeout = 5

    # Convert to list and sort by priority (prefer primary MX)
    mx_list = sorted(mx_records, key=lambda r: r.preference)

    def check_smtp(mx_host, port):
        try:
            if port == 465:
                # Port 465 requires SSL from the start
                with smtplib.SMTP_SSL(mx_host, port, timeout=timeout) as server:
                    server.set_debuglevel(0)
                    server.ehlo()
                    server.mail('<>')
                    code, message = server.rcpt(f'<{email}>')
            else:
                # Ports 587 and 25 - simple SMTP without TLS
                with smtplib.SMTP(mx_host, port, timeout=timeout) as server:
                    server.set_debuglevel(0)
                    server.ehlo()
                    # Only use STARTTLS on port 587
                    if port == 587 and server.has_extn('STARTTLS'):
                        server.starttls()
                        server.ehlo()
                    server.mail('<>')
                    code, message = server.rcpt(f'<{email}>')
            
            if code == 250:
                return True, f"SMTP OK: {message.decode() if message else '250 OK'}"
            else:
                return False, f"{code}-{message.decode() if message else 'Unknown error'}"
        except Exception as e:
            return False, f"SMTP connection failed: {str(e)}"

    # Try each MX server in order, without threading
    for mx_record in mx_list:
        mx_host = mx_record.exchange.to_text().rstrip('.')
        
        for port in smtp_ports:
            result, msg = check_smtp(mx_host, port)
            if result:
                return True, msg
            # If we got a 550 response, that means the server responded 
            # with "mailbox does not exist" - this is a definitive answer
            if "550" in msg:
                return False, msg
            # Continue to next port/server
        
    return False, "Could not verify email - all SMTP attempts failed"
