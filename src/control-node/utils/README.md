# Control-node debug tool

This tool is used to collect all control-node related data.

The following information is captured using this tool:
1. Control-node logs (/var/log/contrail)
2. Contrail status for the node
3. Introspect data (Using contrail-control-cli)
4. Sandesh trace buffer (from Introspect page)
5. IFmap Database (from Introspect page)
6. Route Summary (from Introspect page)
7. Gcore 

## How to provide input to the tool:

We need to provide the tool with an input file. This file should be in yaml format
and it should contain the information (control-node ip, username and password) to
access the control-node.

Sample input file is present in Sample.yaml file.

## Where is collected output stored:

All the collected information is stored in a directory under /var/log/ on the system
from where the script is being run. 

## Options to provide to the script:

1. -i --> Input file (MANDATORY)
2. -c --> to compress the output folder where the information is stored
3. -g --> to generate gcore for the control-node and copy the gcore file.
4. -p --> User defined path where the collected information will be saved.
5. -u --> Just a help message on using the tool

## NOTE

This script can be run from anywhere. From a physical server, from a VM, from inside
the control-node. The script only requires the input file (information about the
control-node).

## Dependencies

The script can be used only by python3 or higher. I am mentioning below all the steps to install python3.7, pip and other package dependencies for the script.

NOTE: Please do not have a pip pre-installed with python2.7 or lower than python3. We need to have the pip installed with python3 or higher for us to be able to install other packages. 

Install Python3.7:
yum update
yum groupinstall -y "development tools"
yum install -y zlib-devel bzip2-devel openssl-devel ncurses-devel sqlite-devel readline-devel tk-devel gdbm-devel db4-devel libpcap-devel xz-devel expat-devel
yum install -y wget
wget http://python.org/ftp/python/3.7.0/Python-3.7.0.tar.xz
tar xf Python-3.7.0.tar.xz
cd Python-3.7.0
./configure --prefix=/usr/local --enable-shared LDFLAGS="-Wl,-rpath /usr/local/lib"
yum install libffi-devel
make && make altinstall
strip /usr/local/lib/libpython3.7m.so.1.0

Install python-pip:
wget https://bootstrap.pypa.io/get-pip.py
python3.7 --version
python3.7 get-pip.py

Install other libraries using pip:
pip install future
pip install paramiko
pip install pyyaml

