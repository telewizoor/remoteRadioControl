#!/bin/bash

# Packages
sudo apt-get install -y nodejs npm ffmpeg

# OpenWebRX+ (Bookworm)
# curl -s https://luarvique.github.io/ppa/openwebrx-plus.gpg | sudo gpg --yes --dearmor -o /etc/apt/trusted.gpg.d/openwebrx-plus.gpg
# sudo tee /etc/apt/sources.list.d/openwebrx-plus.list <<<"deb [signed-by=/etc/apt/trusted.gpg.d/openwebrx-plus.gpg] https://luarvique.github.io/ppa/bookworm ./"

# Directory for software
cd ~
mkdir Project
cd Project

# Hamlib
cd ~/Project
git clone https://github.com/Hamlib/Hamlib.git
cd Hamlib
./configure
make
sudo make install

# remoteRadioControl
cd ~/Project
git clone https://github.com/telewizoor/remoteRadioControl.git
cd remoteRadioControl
git pull

cd server
npm init -y
npm install express
cd ..

# env
python3 -m venv env
source env/bin/activate
pip install -r requirements.txt

# Services
cd ~/Project/remoteRadioControl/server
sudo cp rrc_hamlib.service /etc/systemd/system
sudo cp rrc_node.service /etc/systemd/system
sudo systemctl daemon-reload
sudo systemctl enable rrc_hamlib.service
sudo systemctl start rrc_hamlib.service
sudo systemctl enable rrc_node.service
sudo systemctl start rrc_node.service