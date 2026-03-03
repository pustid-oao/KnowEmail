import os
import sys
import csv
import time
import re
import argparse
import concurrent.futures
from lib.validators import is_valid_email_syntax, has_mx_record, verify_email_smtp

def clean_smtp_message(message):
    """Clean SMTP message by removing enhanced status code prefixes."""
    if not message:
        return message
    cleaned = message.replace('\\n5.1.1', ' ')
    cleaned = cleaned.replace('\\n5.2.1', ' ')
    cleaned = cleaned.replace('\\n4.2.2', ' ')
    cleaned = cleaned.replace('\\n4.2.0', ' ')
    cleaned = cleaned.replace('\n5.1.1', ' ')
    cleaned = cleaned.replace('\n5.2.1', ' ')
    cleaned = cleaned.replace('\n4.2.2', ' ')
    cleaned = cleaned.replace('\n4.2.0', ' ')
    cleaned = re.sub(r'\n\d+\.\d+\.\d+\s*', ' ', cleaned)
    cleaned = re.sub(r'^\d+\.\d+\.\d+\s*', '', cleaned)
    cleaned = cleaned.replace('\\n', ' ')
    cleaned = cleaned.replace('\n', ' ')
    cleaned = ' '.join(cleaned.split())
    return cleaned

def verify_single_email(email, debug=False):
    """
    Verify a single email address.
    Returns tuple: (email, status, smtp_message)
    """
    try:
        # Syntax validation
        if not is_valid_email_syntax(email):
            return (email, "Invalid (Syntax)", "Email syntax validation failed")
        
        # MX record check
        domain = email.split('@')[1]
        if not has_mx_record(domain):
            return (email, "Invalid (No MX)", "Domain does not have MX records")
        
        # SMTP verification
        is_valid, smtp_message = verify_email_smtp(email, debug=debug)
        if not is_valid:
            return (email, "Invalid (SMTP)", smtp_message)
        
        return (email, "Valid", smtp_message)
    except Exception as e:
        return (email, "Error", str(e))

def print_banner():
    """Print ASCII art banner."""
    banner = """
╔══════════════════════════════════════════════════════╗
║                                                      ║
║                      KnowEmail                       ║
║                         ***                          ║
║                                                      ║
╚══════════════════════════════════════════════════════╝
"""
    print(banner)

def print_progress_bar(iteration, total, prefix='', suffix='', length=50, fill='█'):
    """Display a progress bar in terminal."""
    percent = f"{100 * (iteration / float(total)):.1f}"
    filled_length = int(length * iteration // total)
    bar = fill * filled_length + '-' * (length - filled_length)
    print(f'\r{prefix} |{bar}| {percent}% {suffix}', end='', flush=True)
    if iteration == total:
        print()

def verify_single_interactive():
    """Interactive single email verification."""
    print("\n" + "=" * 60)
    print("   Single Email Verification Mode")
    print("=" * 60)
    
    email = input("\nEnter email address to verify: ").strip()
    
    if not email:
        print("[ERROR] Email cannot be empty.")
        return
    
    print(f"\n[INFO] Verifying: {email}")
    print("[INFO] This may take a few seconds...\n")
    
    result_email, status, message = verify_single_email(email)
    clean_msg = clean_smtp_message(message)
    
    # Color output (ANSI codes)
    RESET = '\033[0m'
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    
    # Map status to color
    if status == "Valid":
        color = GREEN
    elif status.startswith("Invalid"):
        color = RED
    else:
        color = YELLOW
    
    print(f"\n{color}{'─' * 60}{RESET}")
    print(f"Email: {email}")
    print(f"Status: {color}{status}{RESET}")
    print(f"Message: {clean_msg}")
    print(f"{color}{'─' * 60}{RESET}\n")

def verify_bulk_emails(file_path, output_csv=None, max_workers=50):
    """
    Verify bulk emails from a file.
    Supports .txt files.
    """
    print("\n" + "=" * 60)
    print("   Bulk Email Verification Mode")
    print("=" * 60)
    
    # Load emails from file
    print(f"\n[INFO] Loading emails from: {file_path}")
    
    emails = []
    try:
        if file_path.endswith('.txt'):
            with open(file_path, 'r', encoding='utf-8') as f:
                emails = [line.strip() for line in f.readlines() if line.strip()]
        elif file_path.endswith('.xlsx'):
            import pandas as pd
            df = pd.read_excel(file_path)
            emails = df.iloc[:, 0].astype(str).tolist()
            emails = [e for e in emails if e and e != 'nan']
        else:
            print("[ERROR] Unsupported file format. Use .txt")
            return
    except Exception as e:
        print(f"[ERROR] Failed to read file: {e}")
        return
    
    if not emails:
        print("[ERROR] No emails found in file.")
        return
    
    print(f"[INFO] Loaded {len(emails)} emails")
    print(f"[INFO] Starting verification with {max_workers} workers...\n")
    
    # Track results
    results = []
    smtp_messages = []
    valid_count = 0
    invalid_count = 0
    error_count = 0
    
    start_time = time.time()
    
    # Progress display
    print("  Progress:")
    print("  " + "-" * 50)
    
    # Use ThreadPoolExecutor for parallel verification
    # For bulk, we disable debug output to keep output clean
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_email = {
            executor.submit(verify_single_email, email, False): email 
            for email in emails
        }
        
        completed = 0
        total = len(emails)
        
        for future in concurrent.futures.as_completed(future_to_email):
            completed += 1
            
            try:
                email, status, smtp_msg = future.result()
            except Exception as e:
                email = future_to_email[future]
                status = "Error"
                smtp_msg = str(e)
            
            results.append((email, status))
            smtp_messages.append(smtp_msg)
            
            if status == "Valid":
                valid_count += 1
            elif status.startswith("Invalid"):
                invalid_count += 1
            else:
                error_count += 1
            
            # Update progress
            print_progress_bar(
                completed, total,
                prefix='  ',
                suffix=f' ({completed}/{total}) Valid: {valid_count} | Invalid: {invalid_count}'
            )
    
    elapsed_time = time.time() - start_time
    
    # Summary
    print("\n" + "=" * 60)
    print("  Verification Complete!")
    print("=" * 60)
    print(f"  Total emails: {len(emails)}")
    print(f"  Valid:        {valid_count}")
    print(f"  Invalid:      {invalid_count}")
    print(f"  Errors:       {error_count}")
    print(f"  Time taken:   {elapsed_time:.2f} seconds")
    print("=" * 60)
    
    # Export to CSV if requested
    if output_csv:
        try:
            with open(output_csv, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(["Email", "Status", "SMTP Message"])
                for (email, status), smtp_msg in zip(results, smtp_messages):
                    writer.writerow([email, status, clean_smtp_message(smtp_msg)])
            print(f"\n[SUCCESS] Results exported to: {output_csv}")
        except Exception as e:
            print(f"\n[ERROR] Failed to export CSV: {e}")
    
    # Preview results (first 10)
    if results:
        print("\n  Preview (first 10 results):")
        print("  " + "-" * 50)
        for i, (email, status) in enumerate(results[:10]):
            if status == "Valid":
                symbol = "✓"
            elif status.startswith("Invalid"):
                symbol = "✗"
            else:
                symbol = "⚠"
            print(f"  {i+1:2d}. [{symbol}] {email:<40} {status}")
        
        if len(results) > 10:
            print(f"  ... and {len(results) - 10} more")
        print()

def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description='KnowEmail - Terminal Email Verifier',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""

Examples:
  # Single email verification
  python main_cli.py --email user@example.com
  
  # Bulk verification from text file
  python main_cli.py --file emails.txt
  
  # Bulk verification with CSV export
  python main_cli.py --file emails.txt --output results.csv
  
  # Interactive mode (no arguments)
  python main_cli.py
        """
    )
    
    parser.add_argument(
        '-e', '--email',
        help='Verify a single email address'
    )
    
    parser.add_argument(
        '-f', '--file',
        help='Path to file containing emails (.txt only)'
    )
    
    parser.add_argument(
        '-o', '--output',
        help='Output CSV file for bulk verification results'
    )
    
    parser.add_argument(
        '-w', '--workers',
        type=int,
        default=50,
        help='Number of concurrent workers for bulk verification (default: 50)'
    )
    
    parser.add_argument(
        '--no-banner',
        action='store_true',
        help='Do not display the banner'
    )
    
    args = parser.parse_args()
    
    # Display banner unless suppressed
    if not args.no_banner:
        print_banner()
    
    # Determine mode
    if args.email:
        # Single email mode - enable debug output for detailed feedback
        print(f"\n[INFO] Single email mode: {args.email}")
        result_email, status, message = verify_single_email(args.email, debug=True)
        clean_msg = clean_smtp_message(message)
        
        # Color output
        RESET = '\033[0m'
        GREEN = '\033[92m'
        RED = '\033[91m'
        
        # Map status to color
        if status == "Valid":
            color = GREEN
        else:
            color = RED
        
        print(f"\n{color}Result: {RESET}")
        print(f"Status: {color}{status}{RESET}")
        print(f"Message: {clean_msg}\n")
        
    elif args.file:
        # Bulk verification mode - disable debug output for cleaner results
        verify_bulk_emails(args.file, args.output, args.workers)
    
    else:
        # Interactive mode
        print("\nChoose verification mode:")
        print("  1. Single email verification")
        print("  2. Bulk verification from file")
        print("  0. Exit")
        print()
        
        choice = input("Enter choice [1/2/0]: ").strip()
        
        if choice == '1':
            verify_single_interactive()
        elif choice == '2':
            file_path = input("Enter path to email list file (.txt or .xlsx): ").strip()
            if file_path:
                output_csv = input("Enter output CSV file (optional, press Enter to skip): ").strip()
                verify_bulk_emails(file_path, output_csv if output_csv else None, args.workers)
            else:
                print("[ERROR] File path cannot be empty.")
        elif choice == '0':
            print("Goodbye!")
        else:
            print("[ERROR] Invalid choice.")

if __name__ == '__main__':
    main()
