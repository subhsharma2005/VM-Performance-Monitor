# VM-Performance-Monitor
VM Performance Monitor &amp; Controller, a cross-platform desktop application designed to provide real-time system monitoring and remote administrative control over virtual machines (VMs)
The VM Performance Monitor & Controller is a robust, cross-platform desktop application designed to provide system administrators and developers with a secure, real-time interface for managing remote Virtual Machines (VMs). The project's architecture is built on three key layers: Secure Communication, Asynchronous Monitoring, and Interactive Presentation.

Architectural Approach and Core Technology

The application operates on a secure client-server model using the Secure Shell (SSH) protocol for all remote operations.

Communication Layer: The Paramiko library serves as the secure backend engine, managing encrypted connections and command execution within the dedicated VMConnection class.

Concurrency Model: To ensure the User Interface (UI) remains responsive during potentially slow network operations, the application uses multi-threading. A background thread continuously fetches data from the VM, while the main thread manages the UI, preventing application freezing.

User Interface: The interface is built using CustomTkinter, delivering a modern, dark-themed, and highly responsive Graphical User Interface (GUI).

Key Functional Deliverables

The tool is divided into two primary functional areas: Passive Monitoring and Active Control.

Passive Monitoring Dashboard:

Provides a real-time system status display, fetching live metrics like CPU Utilization (using top) and Memory Usage (using free) directly from the remote VM.

The UI features color-coded progress bars and labels that visually indicate resource load, shifting colors (Green, Yellow, Red) based on predefined thresholds.

Active Process and Command Control:

Dynamic Process Manager: Presents a sortable, continually updated list of the VM's running processes (PID, User, CPU%, Command) fetched using ps aux. The display is optimized to minimize flicker by updating existing table rows rather than redrawing the entire list.

Process Lifecycle Management: Allows users to gracefully Kill (SIGTERM) or Force Kill (SIGKILL) processes by PID, incorporating critical checks to prevent accidental termination of essential system services (e.g., sshd).

Integrated Command Panel: Features a secure terminal interface for executing arbitrary shell commands, complete with clear output logging and a dedicated prompt to handle Sudo passwords for privileged operations.
