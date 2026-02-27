import re
import dns.resolver
import smtplib
import socket
import concurrent.futures
from cachetools import TTLCache

# Cache for MX records
cache = TTLCache(maxsize=100, ttl=600)

def is_valid_email_syntax(email):
    regex = r'^\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    return re.match(regex, email) is not None

def has_mx_record(domain):
    try:
        resolver = dns.resolver.Resolver()
        resolver.lifetime = 10.0
        mx_records = resolver.resolve(domain, 'MX')
        return bool(mx_records)
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.resolver.LifetimeTimeout):
        return False

def verify_email_smtp(email):
    domain = email.split('@')[1]
    try:
        resolver = dns.resolver.Resolver()
        resolver.nameservers = ['8.8.8.8', '1.1.1.1']
        resolver.lifetime = 3.0
        mx_records = resolver.resolve(domain, 'MX')
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.resolver.LifetimeTimeout):
        return False

    if not mx_records:
        return False

    smtp_ports = [587, 465, 25]
    timeout = 3

    def check_smtp(mx_record, port):
        try:
            with smtplib.SMTP(mx_record.exchange.to_text(), port, timeout=timeout) as server:
                server.set_debuglevel(0)
                server.helo()
                server.mail('')
                code, message = server.rcpt(email)
                if code == 250:
                    return True
        except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, 
                smtplib.SMTPException, socket.timeout):
            return False

    def check_record(mx_record):
        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = [executor.submit(check_smtp, mx_record, port) for port in smtp_ports]
            for future in concurrent.futures.as_completed(futures):
                if future.result():
                    return True
        return False

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [executor.submit(check_record, mx_record) for mx_record in mx_records]
        for future in concurrent.futures.as_completed(futures):
            if future.result():
                return True

    return False