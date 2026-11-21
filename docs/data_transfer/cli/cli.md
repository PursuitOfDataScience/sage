# CLI
## SFTP
SFTP is the SSH-based file transfer protocol that provides access, transfer, and interactive file management over any reliable data stream.  

Example: Start an interactive SFTP session with Midway3 (then use `get` and `put` to download and upload files)

`sftp jdoe@midway3.rcc.uchicago.edu`

## Rsync 
[Rsync](https://rsync.samba.org/) is a fast and versatile file transfer tool that keeps track of progress and the differences between the source and destination. There are many optimizations under the hood that make rsync transfer files faster than ```scp```. More information on the ```rsync``` command can be found at [the rsync man page](https://www.unix.com/man-page/redhat/1/rsync/).

Example 1: Copy/synchronize folder ```tests``` from Midway3 to your current directory

`rsync -avzh jdoe@midway3.rcc.uchicago.edu:/home/jdoe/Documents/tests .`

Example 2: Copy/synchronize folder ```tests``` from your current directory to Midway3

`rsync -avzh tests jdoe@midway3.rcc.uchicago.edu:/home/jdoe/Documents/`

## Wget/Curl 

Wget is a simple command useful for copying files from the Internet to a user's file space on the cluster. Running the line
`wget http://www.examplesite.com/examplefile.txt` downloads `examplefile.txt` to the user's working directory. `curl -O <URL>` works similarly.

## SCP
To copy specific files and folders from your personal computer (client) to RCC clusters (host) through the SSH protocol, you can use the following command, known as `SCP` (secure copy protocol).

Open `Terminal` (macOS) or `Windows PowerShell` (Windows):

`scp <sourceFile> <CNetID>@<hostAddress>:<targetPath>`

Example 1-a: Copying a single file from Jane's personal computer (client) to Dr. Pepper's `project` directory:
 
`scp test.txt jdoe@midway3.rcc.uchicago.edu:/project/drpepper/users/jdoe/`

Example 1-b: Copying a single file from Jane's personal computer (client) to her `home` directory:
 
`scp test.txt jdoe@midway3.rcc.uchicago.edu:/home/jdoe/Documents/`

Example 2-a: Copying a directory (collection of files) from Jane's personal computer (client) to Dr. Pepper's `project` directory:


`scp -r tests jdoe@midway3.rcc.uchicago.edu:/project/drpepper/users/jdoe/`

On macOS, you need to add ```-O``` if there is no folder with the same name on the target server:

`scp -O -r tests jdoe@midway3.rcc.uchicago.edu:/project/drpepper/users/jdoe/`

Example 2-b: Copying a directory (collection of files) from Jane's personal computer (client) to her `home` directory:

`scp -r tests jdoe@midway3.rcc.uchicago.edu:/home/jdoe/Documents/`

After pressing `enter` on your keyboard, the rest is the same as logging into RCC clusters through SSH. 