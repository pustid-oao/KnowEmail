<div align="center">

<picture>
  <img alt="knowemaill logo" src="src/logo.png" width="100%">
</picture>

An Open Source Email Verifier & Validator.
<h3>

By [OpenInitia](https://github.com/OpenInitia)

</h3>

[![GitHub language](https://img.shields.io/github/languages/top/OpenInitia/KnowEmail)](https://github.com/OpenInitia/KnowEmail)
[![GitHub Repo stars](https://img.shields.io/github/stars/OpenInitia/KnowEmail)](https://img.shields.io/github/stars/OpenInitia/KnowEmail)
[![GitHub issues](https://img.shields.io/github/issues/OpenInitia/KnowEmail)](https://github.com/OpenInitia/KnowEmail/issues)
[![GitHub contributors](https://img.shields.io/github/contributors/OpenInitia/KnowEmail)](https://github.com/OpenInitia/KnowEmail/graphs/contributors)
[![GitHub license](https://img.shields.io/github/license/OpenInitia/KnowEmail)](https://github.com/OpenInitia/KnowEmail/blob/main/LICENSE)

</div>

KnowEmail is a robust, open-source email verification and validation tool. It verifies email addresses through syntax validation, MX record checking, and direct SMTP verification to determine if an inbox actually exists.

## Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Usage](#usage)
- [Contributing](#contributing)
- [License](#license)

## Features

- **Syntax Validation:** Ensures the email address adheres to proper format.
- **MX Record Check:** Confirms the domain has valid DNS MX records.
- **SMTP Verification:** Connects to mail servers to verify if the mailbox actually exists.
- **Bulk Verification:** Verify thousands of emails from .txt or .xlsx files with parallel processing.
- **Export Results:** Export bulk verification results to CSV.
- **Dual Interface:** Available as both GUI (PyQt5) and CLI application.

## Installation

```bash
# Clone the repository
git clone https://github.com/pustid-oao/KnowEmail.git
cd KnowEmail

# Install dependencies
pip install -r requirements.txt
```

## Usage

### GUI Version

```bash
python main.py
```

### CLI Version

```bash
# Single email verification
python main_cli.py -e user@example.com

# Bulk verification from file
python main_cli.py -f emails.txt

# Bulk verification with CSV export
python main_cli.py -f emails.txt -o results.csv

# Interactive mode
python main_cli.py
```

### Options

| Flag | Description |
|------|-------------|
| `-e, --email` | Single email to verify |
| `-f, --file` | Path to email list (.txt or .xlsx) |
| `-o, --output` | Output CSV file for results |
| `-w, --workers` | Concurrent workers (default: 50) |

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request or open an issue.

## License

This project is licensed under the [GNU GPL 3.0 License](LICENSE).
