# VM Performance Monitor & Controller

A cross-platform desktop application for monitoring and managing virtual machines over SSH.

## Overview

VM Performance Monitor & Controller provides a modern GUI for administrators and developers to connect to a VM, view live system metrics, inspect running processes, execute shell commands, and manage processes remotely.

The application is built with:

- **Python**
- **CustomTkinter** for the desktop interface
- **Paramiko** for SSH communication
- **psutil** for local dependency support

## Features

### Real-Time Monitoring
- Live CPU usage monitoring
- Live memory usage monitoring
- Color-coded resource indicators
- Periodic refresh of remote system data

### Process Management
- View remote process list
- Sort processes by CPU usage
- Kill processes gracefully
- Force kill processes when needed
- Protection against terminating critical system processes

### Remote Command Execution
- Execute shell commands on the VM
- Support for `sudo` commands with password prompt
- Background execution for long-running commands
- Output and error logging in the GUI

### Connection Management
- SSH connection dialog
- Save connection settings locally
- Reconnect and disconnect controls
- Connection status indicator

### System Details
- VM OS information
- Kernel version
- Uptime
- CPU details
- Disk usage
- Network address information

## Architecture

The application uses a secure client-server model over SSH:

- **VMConnection** handles SSH connectivity and command execution
- **VMMonitor** builds the main interface and orchestrates updates
- **CommandPanel** provides a terminal-like interface for remote commands
- Background threads keep the UI responsive during remote operations

## Screenshots

_Add screenshots here if available._

## Requirements

- Python 3.10+ recommended
- SSH access to a Linux-based VM
- The following Python packages:
  - `paramiko`
  - `psutil`
  - `customtkinter`

## Installation

```bash
pip install paramiko psutil customtkinter
```

## Usage

1. Run the application:

```bash
python main.py
```

2. Enter the VM host/IP, SSH port, username, and password.
3. Connect to the VM.
4. Monitor system metrics, manage processes, or run commands from the dashboard.

## Configuration

Connection settings can be saved locally in `vm_config.json`.

> **Warning:** saved credentials are stored in plain text.

## Project Structure

```text
.
├── main.py
└── README.md
```

## Security Notes

- The app uses SSH for encrypted remote communication.
- Do not store credentials on shared systems unless you trust the environment.
- Be careful when using force kill or remote command execution.

## Limitations

- Designed primarily for Linux VMs with standard Unix command-line tools available.
- Requires SSH access to the remote machine.
- Some metrics depend on common Linux utilities such as `top`, `free`, `ps`, `uname`, and `df`.

## Author

Built by **team valor**.
