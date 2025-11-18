"""
VM Performance Monitor & Controller
A tool for monitoring and controlling processes on virtual machines
Author: team valor
Version: 2.0
"""

import paramiko
import psutil
import customtkinter as ctk
from tkinter import messagebox, scrolledtext
import threading
import time
from collections import deque
import json
import os
from typing import Dict, List, Optional

# ==================== CONFIGURATION ====================
CONFIG_FILE = "vm_config.json"
REFRESH_RATE = 2000  # milliseconds (increased for remote connections)
HISTORY_LENGTH = 60
CPU_THRESHOLD = 20.0
MEMORY_THRESHOLD = 500
MAX_DISPLAYED_PROCESSES = 50

CRITICAL_PROCESSES = {
    'systemd', 'init', 'sshd', 'kernel', 'kthreadd'
}

# ==================== THEME ====================
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

BG_COLOR = "#1a1a1a"
PANEL_COLOR = "#2b2b2b"
ACCENT_COLOR = "#3b8ed0"
WARNING_COLOR = "#ff6b6b"
SUCCESS_COLOR = "#4ade80"
TEXT_COLOR = "#e0e0e0"

# ==================== VM CONNECTION MANAGER ====================
class VMConnection:
    """Manages SSH connection to virtual machine"""
    
    def __init__(self):
        self.client: Optional[paramiko.SSHClient] = None
        self.connected = False
        self.host = ""
        self.port = 22
        self.username = ""
        self.password = ""
        
    def connect(self, host: str, port: int, username: str, password: str) -> tuple:
        """Connect to VM via SSH"""
        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.client.connect(
                hostname=host,
                port=port,
                username=username,
                password=password,
                timeout=10,
                banner_timeout=10
            )
            self.connected = True
            self.host = host
            self.port = port
            self.username = username
            self.password = password
            return True, "Connected successfully"
        except paramiko.AuthenticationException:
            return False, "Authentication failed. Check credentials."
        except paramiko.SSHException as e:
            return False, f"SSH error: {str(e)}"
        except Exception as e:
            return False, f"Connection failed: {str(e)}"
    
    def disconnect(self):
        """Close SSH connection"""
        if self.client:
            self.client.close()
            self.connected = False
    
    def execute_command(self, command: str, sudo_password: str = None) -> tuple:
        """Execute command on VM
        
        Args:
            command: Command to execute
            sudo_password: Optional password for sudo commands (if command starts with sudo)
        """
        if not self.connected:
            return False, "Not connected to VM", ""
        
        try:
            # Check if command starts with sudo and password is provided
            if command.strip().startswith('sudo ') and sudo_password:
                # Use sudo -S to read password from stdin
                # Remove 'sudo ' prefix and add 'sudo -S ' instead
                actual_command = command.replace('sudo ', 'sudo -S ', 1)
                stdin, stdout, stderr = self.client.exec_command(actual_command, timeout=30)
                # Send password via stdin
                stdin.write(sudo_password + '\n')
                stdin.flush()
            else:
                stdin, stdout, stderr = self.client.exec_command(command, timeout=30)
            
            output = stdout.read().decode('utf-8', errors='ignore')
            error = stderr.read().decode('utf-8', errors='ignore')
            exit_code = stdout.channel.recv_exit_status()
            
            return exit_code == 0, output, error
        except Exception as e:
            return False, "", f"Command execution failed: {str(e)}"
    
    def get_system_stats(self) -> Dict:
        """Get system statistics from VM"""
        if not self.connected:
            return {}
        
        try:
            # CPU usage
            success, cpu_out, _ = self.execute_command(
                "top -bn1 | grep 'Cpu(s)' | awk '{print $2}' | cut -d'%' -f1"
            )
            cpu_percent = float(cpu_out.strip()) if success and cpu_out.strip() else 0.0
            
            # Memory usage
            success, mem_out, _ = self.execute_command(
                "free | grep Mem | awk '{print $3/$2 * 100.0, $2, $3}'"
            )
            if success and mem_out.strip():
                parts = mem_out.strip().split()
                mem_percent = float(parts[0])
                mem_total = int(parts[1]) / 1024  # MB
                mem_used = int(parts[2]) / 1024   # MB
            else:
                mem_percent, mem_total, mem_used = 0.0, 0.0, 0.0
            
            return {
                'cpu_percent': cpu_percent,
                'memory_percent': mem_percent,
                'memory_total': mem_total,
                'memory_used': mem_used
            }
        except Exception as e:
            print(f"Error getting system stats: {e}")
            return {}
    
    def get_processes(self) -> List[Dict]:
        """Get process list from VM"""
        if not self.connected:
            return []
        
        try:
            # Get process info using ps command
            cmd = "ps aux --sort=-%cpu | head -n 100"
            success, output, _ = self.execute_command(cmd)
            
            if not success:
                return []
            
            processes = []
            lines = output.strip().split('\n')[1:]  # Skip header
            
            for line in lines:
                parts = line.split(None, 10)
                if len(parts) >= 11:
                    try:
                        processes.append({
                            'user': parts[0],
                            'pid': int(parts[1]),
                            'cpu': float(parts[2]),
                            'memory_percent': float(parts[3]),
                            'vsz': int(parts[4]),  # Virtual memory size
                            'rss': int(parts[5]),  # Resident set size
                            'tty': parts[6],
                            'stat': parts[7],
                            'start': parts[8],
                            'time': parts[9],
                            'name': parts[10][:50]  # Truncate long names
                        })
                    except (ValueError, IndexError):
                        continue
            
            # Sort by CPU usage in descending order
            processes.sort(key=lambda x: x['cpu'], reverse=True)
            
            return processes
        except Exception as e:
            print(f"Error getting processes: {e}")
            return []
    
    def kill_process(self, pid: int, force: bool = False) -> tuple:
        """Kill a process on the VM"""
        if not self.connected:
            return False, "Not connected to VM"
        
        signal = "-9" if force else "-15"
        success, output, error = self.execute_command(f"kill {signal} {pid}")
        
        if success:
            return True, f"Process {pid} terminated"
        else:
            return False, error or "Failed to kill process"
    
    def start_process(self, command: str) -> tuple:
        """Start a new process on the VM"""
        if not self.connected:
            return False, "Not connected to VM", ""
        
        # Run in background and return immediately
        full_cmd = f"nohup {command} > /dev/null 2>&1 & echo $!"
        success, output, error = self.execute_command(full_cmd)
        
        if success:
            pid = output.strip()
            return True, f"Process started with PID: {pid}", ""
        else:
            return False, "Failed to start process", error

# ==================== CONNECTION DIALOG ====================
class ConnectionDialog(ctk.CTkToplevel):
    """Dialog for VM connection settings"""
    
    def __init__(self, parent, callback):
        super().__init__(parent)
        
        self.callback = callback
        self.result = None
        
        self.title("Connect to Virtual Machine")
        self.geometry("500x450")
        self.configure(fg_color=BG_COLOR)
        self.resizable(False, False)
        
        # Make dialog modal
        self.transient(parent)
        self.grab_set()
        
        # Center the dialog on screen
        self.update_idletasks()
        x = (self.winfo_screenwidth() // 2) - (500 // 2)
        y = (self.winfo_screenheight() // 2) - (450 // 2)
        self.geometry(f"500x450+{x}+{y}")
        
        # Make sure dialog is on top and visible
        self.lift()
        self.focus()
        
        self.create_widgets()
        self.load_saved_config()
        
        # Focus on host entry
        self.after(100, lambda: self.host_entry.focus())
        
    def create_widgets(self):
        """Create dialog widgets"""
        # Title
        title = ctk.CTkLabel(
            self, text="🖥️ VM Connection Settings",
            font=("Roboto", 20, "bold"), text_color=ACCENT_COLOR
        )
        title.pack(pady=20)
        
        # Form frame
        form_frame = ctk.CTkFrame(self, fg_color=PANEL_COLOR)
        form_frame.pack(padx=30, pady=10, fill="both", expand=True)
        
        # Host
        ctk.CTkLabel(form_frame, text="Host/IP Address:", 
                    font=("Roboto", 12)).pack(anchor="w", padx=20, pady=(20, 5))
        self.host_entry = ctk.CTkEntry(form_frame, width=400, height=35,
                                       placeholder_text="192.168.1.100")
        self.host_entry.pack(padx=20)
        self.host_entry.bind("<Return>", lambda e: self.on_connect())
        
        # Port
        ctk.CTkLabel(form_frame, text="SSH Port:", 
                    font=("Roboto", 12)).pack(anchor="w", padx=20, pady=(15, 5))
        self.port_entry = ctk.CTkEntry(form_frame, width=400, height=35,
                                       placeholder_text="22")
        self.port_entry.pack(padx=20)
        self.port_entry.insert(0, "22")
        self.port_entry.bind("<Return>", lambda e: self.on_connect())
        
        # Username
        ctk.CTkLabel(form_frame, text="Username:", 
                    font=("Roboto", 12)).pack(anchor="w", padx=20, pady=(15, 5))
        self.username_entry = ctk.CTkEntry(form_frame, width=400, height=35,
                                           placeholder_text="username")
        self.username_entry.pack(padx=20)
        self.username_entry.bind("<Return>", lambda e: self.on_connect())
        
        # Password
        ctk.CTkLabel(form_frame, text="Password:", 
                    font=("Roboto", 12)).pack(anchor="w", padx=20, pady=(15, 5))
        self.password_entry = ctk.CTkEntry(form_frame, width=400, height=35,
                                           placeholder_text="password", show="•")
        self.password_entry.pack(padx=20)
        self.password_entry.bind("<Return>", lambda e: self.on_connect())
        
        # Save credentials checkbox
        self.save_var = ctk.CTkCheckBox(
            form_frame, text="Save connection settings (stored in plain text)",
            font=("Roboto", 10)
        )
        self.save_var.pack(pady=(15, 20))
        
        # Buttons
        button_frame = ctk.CTkFrame(self, fg_color=BG_COLOR)
        button_frame.pack(pady=10)
        
        # Store connect button reference
        self.connect_btn = ctk.CTkButton(
            button_frame, text="🔌 Connect", width=180, height=45,
            fg_color=SUCCESS_COLOR, hover_color="#3bc76a",
            command=self.on_connect, font=("Roboto", 15, "bold")
        )
        self.connect_btn.pack(side="left", padx=10)
        
        ctk.CTkButton(
            button_frame, text="Cancel", width=150, height=45,
            fg_color="#6b6b6b", hover_color="#5b5b5b",
            command=self.on_cancel, font=("Roboto", 14, "bold")
        ).pack(side="left", padx=10)
        
        # Bind Enter key to connect
        self.bind("<Return>", lambda e: self.on_connect())
    
    def load_saved_config(self):
        """Load saved connection settings"""
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    config = json.load(f)
                    self.host_entry.insert(0, config.get('host', ''))
                    self.port_entry.delete(0, 'end')
                    self.port_entry.insert(0, config.get('port', '22'))
                    self.username_entry.insert(0, config.get('username', ''))
                    self.password_entry.insert(0, config.get('password', ''))
            except Exception as e:
                print(f"Error loading config: {e}")
    
    def save_config(self):
        """Save connection settings"""
        try:
            config = {
                'host': self.host_entry.get(),
                'port': int(self.port_entry.get()),
                'username': self.username_entry.get(),
                'password': self.password_entry.get()
            }
            with open(CONFIG_FILE, 'w') as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            print(f"Error saving config: {e}")
    
    def on_connect(self):
        """Handle connect button"""
        host = self.host_entry.get().strip()
        port_str = self.port_entry.get().strip()
        username = self.username_entry.get().strip()
        password = self.password_entry.get()
        
        if not all([host, port_str, username, password]):
            messagebox.showerror("Error", "All fields are required")
            return
        
        try:
            port = int(port_str)
        except ValueError:
            messagebox.showerror("Error", "Port must be a number")
            return
        
        if self.save_var.get():
            self.save_config()
        
        self.result = {
            'host': host,
            'port': port,
            'username': username,
            'password': password
        }
        
        self.grab_release()
        self.destroy()
        self.callback(self.result)
    
    def on_cancel(self):
        """Handle cancel button"""
        self.grab_release()
        self.destroy()

# ==================== COMMAND EXECUTOR ====================
class CommandPanel(ctk.CTkFrame):
    """Panel for executing commands on VM"""
    
    def __init__(self, parent, vm_connection, **kwargs):
        super().__init__(parent, fg_color=PANEL_COLOR, **kwargs)
        
        self.vm = vm_connection
        
        # Title
        title = ctk.CTkLabel(
            self, text="⚡ Command Executor",
            font=("Roboto", 16, "bold"), text_color=ACCENT_COLOR
        )
        title.pack(pady=10)
        
        # Command input
        input_frame = ctk.CTkFrame(self, fg_color=PANEL_COLOR)
        input_frame.pack(fill="x", padx=10, pady=5)
        
        ctk.CTkLabel(input_frame, text="Command:", 
                    font=("Roboto", 12)).pack(side="left", padx=(0, 10))
        
        self.command_entry = ctk.CTkEntry(
            input_frame, placeholder_text="Enter command to execute...",
            height=35
        )
        self.command_entry.pack(side="left", fill="x", expand=True, padx=5)
        self.command_entry.bind("<Return>", lambda e: self.execute_command())
        
        ctk.CTkButton(
            input_frame, text="Execute", width=100, height=35,
            fg_color=SUCCESS_COLOR, hover_color="#3bc76a",
            command=self.execute_command
        ).pack(side="left", padx=5)
        
        ctk.CTkButton(
            input_frame, text="Clear", width=80, height=35,
            fg_color="#6b6b6b", hover_color="#5b5b5b",
            command=self.clear_output
        ).pack(side="left")
        
        # Output area
        output_label = ctk.CTkLabel(
            self, text="Output:", font=("Roboto", 11),
            text_color=TEXT_COLOR
        )
        output_label.pack(anchor="w", padx=10, pady=(10, 2))
        
        # Using tkinter's ScrolledText for output
        import tkinter as tk
        self.output_text = scrolledtext.ScrolledText(
            self, wrap=tk.WORD, width=80, height=10,
            bg="#1a1a1a", fg=TEXT_COLOR, font=("Consolas", 10),
            insertbackground=TEXT_COLOR
        )
        self.output_text.pack(fill="both", expand=True, padx=10, pady=(0, 10))
    
    def execute_command(self):
        """Execute command on VM"""
        command = self.command_entry.get().strip()
        if not command:
            return
        
        self.output_text.insert("end", f"$ {command}\n", "command")
        self.output_text.see("end")
        self.update()
        
        # Check if command starts with sudo
        if command.strip().startswith('sudo '):
            # Prompt for sudo password
            self._prompt_sudo_password(command)
        else:
            # Execute in thread to avoid blocking UI
            thread = threading.Thread(target=self._execute_thread, args=(command, None))
            thread.daemon = True
            thread.start()
    
    def _prompt_sudo_password(self, command):
        """Prompt for sudo password"""
        # Create password dialog
        dialog = ctk.CTkToplevel(self)
        dialog.title("Sudo Password Required")
        dialog.geometry("400x200")
        dialog.configure(fg_color=BG_COLOR)
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()
        
        # Center dialog
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (400 // 2)
        y = (dialog.winfo_screenheight() // 2) - (200 // 2)
        dialog.geometry(f"400x200+{x}+{y}")
        dialog.lift()
        dialog.focus()
        
        # Title
        title = ctk.CTkLabel(
            dialog, text="🔐 Sudo Password Required",
            font=("Roboto", 16, "bold"), text_color=ACCENT_COLOR
        )
        title.pack(pady=20)
        
        # Password entry
        password_frame = ctk.CTkFrame(dialog, fg_color=PANEL_COLOR)
        password_frame.pack(padx=30, pady=10, fill="x")
        
        ctk.CTkLabel(password_frame, text="Password:", 
                    font=("Roboto", 12)).pack(anchor="w", padx=20, pady=(15, 5))
        password_entry = ctk.CTkEntry(
            password_frame, width=300, height=35,
            placeholder_text="Enter sudo password", show="•"
        )
        password_entry.pack(padx=20, pady=(0, 15))
        password_entry.focus()
        password_entry.bind("<Return>", lambda e: self._handle_password_dialog(dialog, password_entry, command))
        
        # Buttons
        button_frame = ctk.CTkFrame(dialog, fg_color=BG_COLOR)
        button_frame.pack(pady=10)
        
        ctk.CTkButton(
            button_frame, text="OK", width=120, height=35,
            fg_color=SUCCESS_COLOR, hover_color="#3bc76a",
            command=lambda: self._handle_password_dialog(dialog, password_entry, command),
            font=("Roboto", 14, "bold")
        ).pack(side="left", padx=10)
        
        ctk.CTkButton(
            button_frame, text="Cancel", width=120, height=35,
            fg_color="#6b6b6b", hover_color="#5b5b5b",
            command=lambda: [dialog.grab_release(), dialog.destroy()],
            font=("Roboto", 14, "bold")
        ).pack(side="left", padx=10)
    
    def _handle_password_dialog(self, dialog, password_entry, command):
        """Handle password dialog submission"""
        password = password_entry.get()
        dialog.grab_release()
        dialog.destroy()
        
        if not password:
            self.output_text.insert("end", "Command cancelled (no password provided)\n", "error")
            self.output_text.see("end")
            return
        
        # Execute in thread with password
        thread = threading.Thread(target=self._execute_thread, args=(command, password))
        thread.daemon = True
        thread.start()
    
    def _execute_thread(self, command, sudo_password):
        """Execute command in background thread"""
        success, output, error = self.vm.execute_command(command, sudo_password)
        
        self.after(0, self._display_output, success, output, error)
    
    def _display_output(self, success, output, error):
        """Display command output"""
        if success and output:
            self.output_text.insert("end", output + "\n", "output")
        
        if error:
            self.output_text.insert("end", f"Error: {error}\n", "error")
        
        if not success and not error:
            self.output_text.insert("end", "Command failed\n", "error")
        
        self.output_text.insert("end", "\n")
        self.output_text.see("end")
        
        # Configure tags for coloring
        self.output_text.tag_config("command", foreground=ACCENT_COLOR)
        self.output_text.tag_config("error", foreground=WARNING_COLOR)
        self.output_text.tag_config("output", foreground=SUCCESS_COLOR)
    
    def clear_output(self):
        """Clear output area"""
        self.output_text.delete("1.0", "end")

# ==================== MAIN APPLICATION ====================
class VMMonitor(ctk.CTk):
    """Main VM Monitor application"""
    
    def __init__(self):
        super().__init__()
        
        self.title("VM Performance Monitor & Controller v2.0")
        self.geometry("1400x900")
        self.configure(fg_color=BG_COLOR)
        
        # VM Connection
        self.vm = VMConnection()
        
        # Data storage
        self.cpu_history = deque([0] * HISTORY_LENGTH, maxlen=HISTORY_LENGTH)
        self.memory_history = deque([0] * HISTORY_LENGTH, maxlen=HISTORY_LENGTH)
        self.processes = []
        
        # Thread control
        self.running = True
        self.update_thread = None
        
        # Dialog tracking
        self.connection_dialog = None
        
        # Build UI
        self.create_ui()
        
        # Show connection dialog
        self.after(500, self.show_connection_dialog)
        
        # Handle window close
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
    
    def create_ui(self):
        """Create the user interface"""
        # Top bar - Connection status
        self.create_top_bar()
        
        # Main content area
        main_container = ctk.CTkFrame(self, fg_color=BG_COLOR)
        main_container.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Left panel - System stats
        left_panel = ctk.CTkFrame(main_container, fg_color=PANEL_COLOR, width=400)
        left_panel.pack(side="left", fill="y", padx=(0, 10))
        left_panel.pack_propagate(False)
        
        self.create_stats_panel(left_panel)
        
        # Right panel - Process table and commands
        right_panel = ctk.CTkFrame(main_container, fg_color=BG_COLOR)
        right_panel.pack(side="left", fill="both", expand=True)
        
        # Process table
        self.create_process_panel(right_panel)
        
        # Command executor
        self.command_panel = CommandPanel(right_panel, self.vm, height=300)
        self.command_panel.pack(fill="both", padx=0, pady=(10, 0))
    
    def create_top_bar(self):
        """Create top bar with connection status"""
        top_bar = ctk.CTkFrame(self, fg_color=PANEL_COLOR, height=60)
        top_bar.pack(fill="x", padx=10, pady=(10, 0))
        top_bar.pack_propagate(False)
        
        # Status indicator
        self.status_label = ctk.CTkLabel(
            top_bar, text="⚫ Disconnected",
            font=("Roboto", 14, "bold"), text_color=WARNING_COLOR
        )
        self.status_label.pack(side="left", padx=20)
        
        # VM info
        self.vm_info_label = ctk.CTkLabel(
            top_bar, text="", font=("Roboto", 12), text_color=TEXT_COLOR
        )
        self.vm_info_label.pack(side="left", padx=20)
        
        # Buttons
        self.connect_button = ctk.CTkButton(
            top_bar, text="Connect", width=120, height=35,
            fg_color=SUCCESS_COLOR, hover_color="#3bc76a",
            command=self.show_connection_dialog
        )
        self.connect_button.pack(side="right", padx=10)
        
        self.disconnect_button = ctk.CTkButton(
            top_bar, text="Disconnect", width=120, height=35,
            fg_color=WARNING_COLOR, hover_color="#ff5252",
            command=self.disconnect_vm, state="disabled"
        )
        self.disconnect_button.pack(side="right", padx=10)
    
    def create_stats_panel(self, parent):
        """Create system statistics panel"""
        # Title
        title = ctk.CTkLabel(
            parent, text="📊 System Statistics",
            font=("Roboto", 18, "bold"), text_color=ACCENT_COLOR
        )
        title.pack(pady=15)
        
        # CPU stat
        cpu_frame = ctk.CTkFrame(parent, fg_color="#2a2a2a")
        cpu_frame.pack(fill="x", padx=15, pady=10)
        
        ctk.CTkLabel(cpu_frame, text="CPU Usage", 
                    font=("Roboto", 14, "bold")).pack(pady=(10, 5))
        self.cpu_label = ctk.CTkLabel(
            cpu_frame, text="0.0%", font=("Roboto", 32, "bold"),
            text_color=SUCCESS_COLOR
        )
        self.cpu_label.pack(pady=10)
        
        self.cpu_bar = ctk.CTkProgressBar(cpu_frame, width=300, height=20)
        self.cpu_bar.pack(pady=(0, 15))
        self.cpu_bar.set(0)
        
        # Memory stat
        mem_frame = ctk.CTkFrame(parent, fg_color="#2a2a2a")
        mem_frame.pack(fill="x", padx=15, pady=10)
        
        ctk.CTkLabel(mem_frame, text="Memory Usage", 
                    font=("Roboto", 14, "bold")).pack(pady=(10, 5))
        self.memory_label = ctk.CTkLabel(
            mem_frame, text="0.0%", font=("Roboto", 32, "bold"),
            text_color=SUCCESS_COLOR
        )
        self.memory_label.pack(pady=10)
        
        self.memory_bar = ctk.CTkProgressBar(mem_frame, width=300, height=20)
        self.memory_bar.pack(pady=(0, 5))
        self.memory_bar.set(0)
        
        self.memory_info_label = ctk.CTkLabel(
            mem_frame, text="0 MB / 0 MB", font=("Roboto", 11),
            text_color=TEXT_COLOR
        )
        self.memory_info_label.pack(pady=(0, 15))
        
        # Quick actions
        actions_frame = ctk.CTkFrame(parent, fg_color="#2a2a2a")
        actions_frame.pack(fill="x", padx=15, pady=10)
        
        ctk.CTkLabel(actions_frame, text="Quick Actions", 
                    font=("Roboto", 14, "bold")).pack(pady=(10, 10))
        
        # Connect button - always visible, prominent
        self.main_connect_button = ctk.CTkButton(
            actions_frame, text="🔌 Connect to VM", width=250, height=45,
            fg_color=SUCCESS_COLOR, hover_color="#3bc76a",
            command=self.show_connection_dialog,
            font=("Roboto", 14, "bold")
        )
        self.main_connect_button.pack(pady=5, padx=15)
        
        ctk.CTkButton(
            actions_frame, text="🔄 Refresh Processes", width=250,
            command=self.force_refresh
        ).pack(pady=5, padx=15)
        
        ctk.CTkButton(
            actions_frame, text="🚀 Start Process", width=250,
            command=self.show_start_process_dialog
        ).pack(pady=5, padx=15)
        
        ctk.CTkButton(
            actions_frame, text="📊 System Info", width=250,
            command=self.show_system_info
        ).pack(pady=5, padx=15)
    
    def create_process_panel(self, parent):
        """Create process table panel"""
        panel = ctk.CTkFrame(parent, fg_color=PANEL_COLOR)
        panel.pack(fill="both", expand=True)
        
        # Title
        title = ctk.CTkLabel(
            panel, text="🔧 Process Manager",
            font=("Roboto", 18, "bold"), text_color=ACCENT_COLOR
        )
        title.pack(pady=10)
        
        # Scrollable frame
        self.process_scroll = ctk.CTkScrollableFrame(
            panel, fg_color=BG_COLOR
        )
        self.process_scroll.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        
        # Header
        self.create_process_header()
        
        # Process rows container
        self.process_container = ctk.CTkFrame(
            self.process_scroll, fg_color=BG_COLOR
        )
        self.process_container.pack(fill="both", expand=True)
        
        # Dictionary to store process rows by PID for efficient updates
        self.process_rows = {}  # {pid: {row_widget, labels_dict}}
    
    def create_process_header(self):
        """Create process table header"""
        header = ctk.CTkFrame(self.process_scroll, fg_color=ACCENT_COLOR)
        header.pack(fill="x", pady=(0, 5))
        
        headers = [
            ("PID", 80),
            ("User", 100),
            ("CPU %", 80),
            ("Mem %", 80),
            ("Status", 80),
            ("Command", 300),
            ("Actions", 180)
        ]
        
        for text, width in headers:
            ctk.CTkLabel(
                header, text=text, width=width, font=("Roboto", 12, "bold")
            ).pack(side="left", padx=2, pady=8)
    
    def update_process_display(self):
        """Update process display smoothly"""
        displayed_processes = self.processes[:MAX_DISPLAYED_PROCESSES]
        current_pids = {proc['pid'] for proc in displayed_processes}
        
        # Remove rows for processes that no longer exist
        pids_to_remove = set(self.process_rows.keys()) - current_pids
        for pid in pids_to_remove:
            if pid in self.process_rows:
                row_data = self.process_rows[pid]
                row_data['row'].destroy()
                del self.process_rows[pid]
        
        # Update or create rows for current processes
        for i, proc in enumerate(displayed_processes):
            pid = proc['pid']
            
            if pid in self.process_rows:
                # Update existing row (smooth update - no widget destruction)
                self._update_process_row(pid, proc, i % 2 == 0)
            else:
                # Create new row only for new processes
                self._create_process_row(proc, i % 2 == 0)
    
    def _update_process_row(self, pid, proc, alt_color):
        """Update an existing process row"""
        if pid not in self.process_rows:
            return
        
        row_data = self.process_rows[pid]
        labels = row_data['labels']
        
        # Update background color if needed
        bg = "#2a2a2a" if alt_color else BG_COLOR
        row_data['row'].configure(fg_color=bg)
        
        # Update labels
        labels['user'].configure(text=proc['user'][:10] + "..." if len(proc['user']) > 10 else proc['user'])
        
        # Update CPU with color
        cpu_color = WARNING_COLOR if proc['cpu'] > CPU_THRESHOLD else TEXT_COLOR
        labels['cpu'].configure(text=f"{proc['cpu']:.1f}%", text_color=cpu_color)
        
        labels['memory'].configure(text=f"{proc['memory_percent']:.1f}%")
        labels['stat'].configure(text=proc['stat'])
        
        cmd = proc['name'][:40] + "..." if len(proc['name']) > 40 else proc['name']
        labels['command'].configure(text=cmd)
        
        # Update action frame background
        row_data['action_frame'].configure(fg_color=bg)
    
    def _create_process_row(self, proc, alt_color):
        """Create a new process row and store references"""
        bg = "#2a2a2a" if alt_color else BG_COLOR
        
        row = ctk.CTkFrame(self.process_container, fg_color=bg)
        row.pack(fill="x", pady=1)
        
        # Store labels for efficient updates
        labels = {}
        
        # PID
        ctk.CTkLabel(row, text=str(proc['pid']), width=80,
                    font=("Roboto", 10)).pack(side="left", padx=2)
        
        # User
        user = proc['user'][:10] + "..." if len(proc['user']) > 10 else proc['user']
        labels['user'] = ctk.CTkLabel(row, text=user, width=100,
                    font=("Roboto", 10))
        labels['user'].pack(side="left", padx=2)
        
        # CPU
        cpu_color = WARNING_COLOR if proc['cpu'] > CPU_THRESHOLD else TEXT_COLOR
        labels['cpu'] = ctk.CTkLabel(row, text=f"{proc['cpu']:.1f}%", width=80,
                    font=("Roboto", 10), text_color=cpu_color)
        labels['cpu'].pack(side="left", padx=2)
        
        # Memory
        labels['memory'] = ctk.CTkLabel(row, text=f"{proc['memory_percent']:.1f}%", width=80,
                    font=("Roboto", 10))
        labels['memory'].pack(side="left", padx=2)
        
        # Status
        labels['stat'] = ctk.CTkLabel(row, text=proc['stat'], width=80,
                    font=("Roboto", 10))
        labels['stat'].pack(side="left", padx=2)
        
        # Command
        cmd = proc['name'][:40] + "..." if len(proc['name']) > 40 else proc['name']
        labels['command'] = ctk.CTkLabel(row, text=cmd, width=300,
                    font=("Roboto", 10), anchor="w")
        labels['command'].pack(side="left", padx=2)
        
        # Actions
        action_frame = ctk.CTkFrame(row, fg_color=bg)
        action_frame.pack(side="left", padx=2)
        
        ctk.CTkButton(
            action_frame, text="Kill", width=80, height=25,
            fg_color=WARNING_COLOR, hover_color="#ff5252",
            command=lambda pid=proc['pid'], name=proc['name']: self.kill_process(pid, name, False)
        ).pack(side="left", padx=2)
        
        ctk.CTkButton(
            action_frame, text="Force Kill", width=90, height=25,
            fg_color="#d63031", hover_color="#c92a2a",
            command=lambda pid=proc['pid'], name=proc['name']: self.kill_process(pid, name, True)
        ).pack(side="left", padx=2)
        
        # Store row data for updates
        self.process_rows[proc['pid']] = {
            'row': row,
            'labels': labels,
            'action_frame': action_frame
        }
    
    def show_connection_dialog(self):
        """Show connection dialog"""
        # Prevent multiple dialogs
        if self.connection_dialog is not None:
            try:
                if self.connection_dialog.winfo_exists():
                    self.connection_dialog.lift()
                    self.connection_dialog.focus()
                    return
            except:
                pass
        
        # Create new dialog
        self.connection_dialog = ConnectionDialog(self, self.on_connect)
        
        # Clean up reference when dialog is closed
        def on_dialog_close():
            self.connection_dialog = None
        
        # Monitor dialog destruction
        self.connection_dialog.protocol("WM_DELETE_WINDOW", 
                                       lambda: [on_dialog_close(), self.connection_dialog.destroy()])
    
    def on_connect(self, config):
        """Handle connection attempt"""
        # Clear dialog reference
        self.connection_dialog = None
        
        if not config:
            return
        
        # Show connecting status
        self.status_label.configure(text="🟡 Connecting...", text_color="#fbbf24")
        self.update()
        
        # Try to connect in thread
        thread = threading.Thread(target=self._connect_thread, args=(config,))
        thread.daemon = True
        thread.start()
    
    def _connect_thread(self, config):
        """Connect to VM in background thread"""
        success, message = self.vm.connect(
            config['host'], config['port'],
            config['username'], config['password']
        )
        
        self.after(0, self._connect_callback, success, message, config)
    
    def _connect_callback(self, success, message, config):
        """Handle connection result"""
        if success:
            self.status_label.configure(
                text="🟢 Connected", text_color=SUCCESS_COLOR
            )
            self.vm_info_label.configure(
                text=f"VM: {config['username']}@{config['host']}:{config['port']}"
            )
            # Update button states
            self.connect_button.configure(text="Reconnect")
            self.disconnect_button.configure(state="normal")
            self.main_connect_button.configure(text="🔄 Reconnect to VM")
            messagebox.showinfo("Success", message)
            
            # Start monitoring
            self.start_monitoring()
        else:
            self.status_label.configure(
                text="⚫ Connection Failed", text_color=WARNING_COLOR
            )
            messagebox.showerror("Connection Failed", message)
    
    def disconnect_vm(self):
        """Disconnect from VM"""
        if self.vm.connected:
            self.running = False
            if self.update_thread and self.update_thread.is_alive():
                self.update_thread.join(timeout=3)
            
            self.vm.disconnect()
            self.status_label.configure(
                text="⚫ Disconnected", text_color=WARNING_COLOR
            )
            self.vm_info_label.configure(text="")
            
            # Update button states
            self.connect_button.configure(text="Connect")
            self.disconnect_button.configure(state="disabled")
            self.main_connect_button.configure(text="🔌 Connect to VM")
            
            # Clear displays
            self.cpu_label.configure(text="0.0%")
            self.memory_label.configure(text="0.0%")
            self.cpu_bar.set(0)
            self.memory_bar.set(0)
            self.processes = []
            # Clear process rows dictionary
            self.process_rows.clear()
            self.update_process_display()
            
            messagebox.showinfo("Disconnected", "Disconnected from VM")
    
    def start_monitoring(self):
        """Start monitoring thread"""
        self.running = True
        self.update_thread = threading.Thread(target=self.monitor_loop, daemon=True)
        self.update_thread.start()
    
    def monitor_loop(self):
        """Background monitoring loop"""
        while self.running and self.vm.connected:
            try:
                # Get system stats
                stats = self.vm.get_system_stats()
                
                # Get processes
                processes = self.vm.get_processes()
                
                # Update UI on main thread
                self.after(0, self._update_ui, stats, processes)
                
            except Exception as e:
                print(f"Error in monitor loop: {e}")
                if not self.vm.connected:
                    self.after(0, self._connection_lost)
                    break
            
            time.sleep(REFRESH_RATE / 1000.0)
    
    def _update_ui(self, stats, processes):
        """Update UI with new data"""
        if stats:
            # CPU
            cpu = stats.get('cpu_percent', 0)
            self.cpu_label.configure(text=f"{cpu:.1f}%")
            self.cpu_bar.set(cpu / 100.0)
            
            if cpu < 50:
                self.cpu_label.configure(text_color=SUCCESS_COLOR)
            elif cpu < 75:
                self.cpu_label.configure(text_color="#fbbf24")
            else:
                self.cpu_label.configure(text_color=WARNING_COLOR)
            
            # Memory
            mem = stats.get('memory_percent', 0)
            mem_total = stats.get('memory_total', 0)
            mem_used = stats.get('memory_used', 0)
            
            self.memory_label.configure(text=f"{mem:.1f}%")
            self.memory_bar.set(mem / 100.0)
            self.memory_info_label.configure(
                text=f"{mem_used:.0f} MB / {mem_total:.0f} MB"
            )
            
            if mem < 50:
                self.memory_label.configure(text_color=SUCCESS_COLOR)
            elif mem < 75:
                self.memory_label.configure(text_color="#fbbf24")
            else:
                self.memory_label.configure(text_color=WARNING_COLOR)
        
        # Update processes
        self.processes = processes
        self.update_process_display()
    
    def _connection_lost(self):
        """Handle lost connection"""
        self.status_label.configure(
            text="⚫ Connection Lost", text_color=WARNING_COLOR
        )
        # Update button states
        self.connect_button.configure(text="Connect")
        self.disconnect_button.configure(state="disabled")
        self.main_connect_button.configure(text="🔌 Connect to VM")
        messagebox.showerror(
            "Connection Lost",
            "Lost connection to VM. Please reconnect."
        )
    
    def force_refresh(self):
        """Force refresh of process list"""
        if not self.vm.connected:
            messagebox.showwarning("Not Connected", "Please connect to a VM first")
            return
        
        # Trigger immediate update
        thread = threading.Thread(target=self._force_refresh_thread, daemon=True)
        thread.start()
    
    def _force_refresh_thread(self):
        """Force refresh in background"""
        try:
            stats = self.vm.get_system_stats()
            processes = self.vm.get_processes()
            self.after(0, self._update_ui, stats, processes)
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Error", f"Refresh failed: {e}"))
    
    def kill_process(self, pid, name, force):
        """Kill a process"""
        if not self.vm.connected:
            messagebox.showwarning("Not Connected", "Please connect to a VM first")
            return
        
        # Check if critical
        if any(critical in name.lower() for critical in CRITICAL_PROCESSES):
            messagebox.showerror(
                "Critical Process",
                f"Cannot kill critical system process: {name}"
            )
            return
        
        # Confirm
        action = "Force kill" if force else "Kill"
        result = messagebox.askyesno(
            "Confirm Action",
            f"{action} process?\n\nPID: {pid}\nName: {name}\n\n"
            "This action cannot be undone."
        )
        
        if result:
            thread = threading.Thread(
                target=self._kill_process_thread,
                args=(pid, name, force),
                daemon=True
            )
            thread.start()
    
    def _kill_process_thread(self, pid, name, force):
        """Kill process in background"""
        success, message = self.vm.kill_process(pid, force)
        
        if success:
            self.after(0, lambda: messagebox.showinfo("Success", message))
            self.after(1000, self.force_refresh)  # Refresh after 1 second
        else:
            self.after(0, lambda: messagebox.showerror("Error", message))
    
    def show_start_process_dialog(self):
        """Show dialog to start a new process"""
        if not self.vm.connected:
            messagebox.showwarning("Not Connected", "Please connect to a VM first")
            return
        
        dialog = ctk.CTkInputDialog(
            text="Enter command to execute:",
            title="Start New Process"
        )
        command = dialog.get_input()
        
        if command:
            thread = threading.Thread(
                target=self._start_process_thread,
                args=(command,),
                daemon=True
            )
            thread.start()
    
    def _start_process_thread(self, command):
        """Start process in background"""
        success, message, error = self.vm.start_process(command)
        
        if success:
            self.after(0, lambda: messagebox.showinfo("Success", message))
            self.after(1000, self.force_refresh)
        else:
            self.after(0, lambda: messagebox.showerror(
                "Error", f"{message}\n{error}" if error else message
            ))
    
    def show_system_info(self):
        """Show detailed system information"""
        if not self.vm.connected:
            messagebox.showwarning("Not Connected", "Please connect to a VM first")
            return
        
        thread = threading.Thread(target=self._get_system_info_thread, daemon=True)
        thread.start()
    
    def _get_system_info_thread(self):
        """Get system info in background"""
        commands = {
            "OS Info": "cat /etc/os-release | head -n 5",
            "Kernel": "uname -r",
            "Uptime": "uptime -p",
            "CPU Info": "lscpu | grep 'Model name\\|CPU(s)' | head -n 2",
            "Disk Usage": "df -h / | tail -n 1",
            "Network": "hostname -I"
        }
        
        info_text = "=== VM System Information ===\n\n"
        
        for label, cmd in commands.items():
            success, output, _ = self.vm.execute_command(cmd)
            info_text += f"{label}:\n{output.strip()}\n\n"
        
        self.after(0, lambda: self._show_info_dialog(info_text))
    
    def _show_info_dialog(self, info):
        """Display system info dialog"""
        dialog = ctk.CTkToplevel(self)
        dialog.title("System Information")
        dialog.geometry("600x500")
        dialog.configure(fg_color=BG_COLOR)
        
        import tkinter as tk
        text = scrolledtext.ScrolledText(
            dialog, wrap=tk.WORD, width=70, height=25,
            bg="#1a1a1a", fg=TEXT_COLOR, font=("Consolas", 10)
        )
        text.pack(fill="both", expand=True, padx=20, pady=20)
        text.insert("1.0", info)
        text.configure(state="disabled")
        
        ctk.CTkButton(
            dialog, text="Close", width=150,
            command=dialog.destroy
        ).pack(pady=(0, 20))
    
    def on_closing(self):
        """Handle window close"""
        self.running = False
        
        if self.update_thread and self.update_thread.is_alive():
            self.update_thread.join(timeout=3)
        
        if self.vm.connected:
            self.vm.disconnect()
        
        self.destroy()

# ==================== MAIN ENTRY POINT ====================
if __name__ == "__main__":
    # Check dependencies
    try:
        import paramiko
        import psutil
        import customtkinter
    except ImportError as e:
        print("ERROR: Required dependencies not installed!")
        print("Please install: pip install paramiko psutil customtkinter")
        exit(1)
    
    # Launch application
    app = VMMonitor()
    app.mainloop()