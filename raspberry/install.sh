#!/bin/bash

# Install Sonobus
echo "deb http://pkg.sonobus.net/apt stable main" | sudo tee /etc/apt/sources.list.d/sonobus.list
sudo wget -O /etc/apt/trusted.gpg.d/sonobus.gpg https://pkg.sonobus.net/apt/keyring.gpg
sudo apt update && sudo apt install sonobus

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

# Services, autostart etc
cd ~/Project/remoteRadioControl/raspberry
sudo cp catcontrol.service /etc/systemd/system
sudo cp sonobus.desktop /etc/xdg/autostart
sudo systemctl daemon-reload
sudo systemctl enable catcontrol.service
sudo systemctl start catcontrol.service