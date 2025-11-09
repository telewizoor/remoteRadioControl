Software for ham radio remote control.

Currently configured for Yaesu FT-450D and Hamlib software run on Raspberry Pi4.
OpenWebRX+ for waterfall view.
~~Mumble~~ SonoBus for voice transmission.

**New version with built in waterfall view**
<img width="2052" height="563" alt="rig_w_waterfall" src="https://github.com/user-attachments/assets/4b6b4ae6-f0c1-45b6-9cf6-4f016ff7dfef" />

**tldr:**
0. Raspberry with Bookworm + GUI(for realvnc)
1. Cat cable connected to raspberry and the radio
2. Install and start hamlib daemon(checkout branch?)
3. RTL SDR v4 and tap rf from the radio
4. OpenWebRX+ installed on raspberry + hamlib enabled
5. ZeroTier or local network
6. Install Sonobus on raspberry and run it on startup(/etc/xdg/autostart)
7. Install Sonobus on PC, change buffer size on rapsberry and windows! eg 50ms at start
8. Connect radio output with Raspberry USB audio card input
   Make an adapter for microphone input
   Adjust levels in alsamixer

**Instruction:**
First of all you need to have Raspberry Pi with GUI and VNC configured - it will be used later for SonoBus configuration.
In my setup I have Raspberry connected to the Transceiver with USB-RS232 cable and audio cables - radio output connected to the mic input and mic input connected to the speaker output of USB audio card. For microphone input please take a look at circuit diagram. Mic signal is connected to the tip of mini-jack with 70kOhm resistor in series. Mic gnd and gnd is connected to mini-jack ring with 100nF in series. Input/Output levels must be adjusted using 'alsamixer' command.

For waterfall view I installed special board into the transceiver to get the signal output for SDR.
PAT-V from that shop:
https://www.sdr-kits.net/Panoramic-Adaptor-Tap-Boards
http://huprf.com/huprf/wp-content/uploads/2016/03/PAT-FT450-Installation-Notes-V2.pdf
<img width="1024" height="577" alt="mic_input" src="https://github.com/user-attachments/assets/e8f733e3-7450-4805-ae78-dc12c9599ba7" />
(thanks author for that picture!)
Additionally I am using antenna switch for switching between four different antennas, just fyi that it is possible.

That's about the hardware.

To control the radio I am using hamlib. It will be installed on Raspberry with installation script.
For audio transmission I switched to SonoBus, however Mumble could be used as well(to be honest it is your choice).
If you want to have waterfall view, OpenwebRX+ must be installed.

Last but not least! For remote access outside your local network you need to have something like Zerotier which is 'emulating' local network through the internet connection. It is possible to forward ports and don't use Zerotier however I think it is very risky!
