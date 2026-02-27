import re
import dns.resolver
import smtplib
import socket
import concurrent.futures
from cachetools import TTLCache

# Cache for MX records (keyed by domain, TTL = 10 minutes)
cache = TTLCache(maxsize=100, ttl=600)

def is_valid_email_syntax(email):
    regex = r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'
    return re.match(regex, email) is not None

def has_mx_record(domain):
    if domain in cache:
        return cache[domain]
    try:
        resolver = dns.resolver.Resolver()
        resolver.lifetime = 10.0
        mx_records = resolver.resolve(domain, 'MX')
        result = bool(mx_records)
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.resolver.LifetimeTimeout):
        result = False
    cache[domain] = result
    return result

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
    timeout = 5

    def check_smtp(mx_record, port):
        mx_host = mx_record.exchange.to_text().rstrip('.')
        try:
            if port == 465:
                server = smtplib.SMTP_SSL(mx_host, port, timeout=timeout)
            else:
                server = smtplib.SMTP(mx_host, port, timeout=timeout)

            with server:
                server.set_debuglevel(0)
                if port == 587:
                    server.ehlo()
                    server.starttls()
                    server.ehlo()
                else:
                    server.ehlo()
                server.mail('probe@example.com')
                code, message = server.rcpt(email)
                # 250 = OK, 251 = forwarded — both mean the address is valid.
                # Yahoo and many providers return 250 on port 25 when the
                # address exists; treat any 2xx as success.
                if 200 <= code < 300:
                    return True
                return False
        except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected,
                smtplib.SMTPException, socket.timeout,
                OSError):  # OSError covers ssl.SSLError (TLS failures) and network errors
            return False

    # Use a bounded pool: at most len(mx_records) * len(smtp_ports) tasks
    max_workers = min(10, len(mx_records) * len(smtp_ports))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(check_smtp, mx_record, port): (mx_record, port)
            for mx_record in mx_records
            for port in smtp_ports
        }
        for future in concurrent.futures.as_completed(futures):
            try:
                if future.result():
                    return True
            except Exception:
                continue  # treat unexpected errors as non-confirmations

    return False
