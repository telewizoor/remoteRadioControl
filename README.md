Software for hamradio remote control.

Currently I am using Mumble for Audio - there is an option to use audio client/server from this repo however Mumble is more reliable. With good PC and good internet connection built-in audio should be fine.

Installation by calling install.sh from 'server' folder.
I am using Raspberry with GUI to set the mumble settings, if you want 100% CLI, try to use builtin audio(currently server service is disable and GUI button is hidden).
Software can be used locally just to have convenient radio control + waterfall with audio directly from rig.

Features:
- radio control through Hamlib
- waterfall view(using OpenWebRX+ - thanks for: https://github.com/0xAF/openwebrxplus and https://github.com/luarvique/openwebrx)
- bookmarks(channel memory)
- antenna switch control(relays control from rasberry GPIO)
- DX cluster view on waterfall - very basic :)

Tips:
- click on frequency to open dialog with frequency input
- double click on TUNER to tune tuner :)
- VFOB update is a bit buggy, it will be updated after changing to VFOB
- sometimes after changing band etc, some sliders could have improper values(especially DSP ones)
- DSP settings are milion times easier comparing to the original FT450D interface
- web interace is poorly tested
- Mumble settings: Quality - 32kbps, 40ms. Play with audio settings on server side to adjust volumes.

Contact me with any problems: mz.przemo@gmail.com

73, SP9PHO

<img width="785" height="361" alt="diagram" src="https://github.com/user-attachments/assets/1a334c54-1b8c-43eb-a9d0-89ba19924965" />

<img width="1255" height="442" alt="pythonApp" src="https://github.com/user-attachments/assets/880713f6-7732-411b-97be-ca84f5ea218d" />

<img width="602" height="539" alt="pythonAppSettings" src="https://github.com/user-attachments/assets/2b2c2875-a132-417a-842c-592155ce16cb" />

<img width="1781" height="1240" alt="website" src="https://github.com/user-attachments/assets/5956c8f1-cd67-4d3b-a3cb-e544274dbf9a" />


**Instruction:**
<TODO>
