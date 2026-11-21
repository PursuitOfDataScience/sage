# SAMBA (Network drive) 

SAMBA allows you to connect to (or “mount”) your home and project directories on your local computer.   

!!! Warning
    This method of accessing your RCC home and project space is only available from within the UChicago campus network. From off-campus, you will need to first **connect through the UChicago VPN.**

!!! tip "Note"
    While transferring large files and/or datasets over SAMBA may be appealing, it slows file transfer for all other users. **Please use Globus for large transfers**.

## Connecting from Windows   

On a Windows computer, select “Map Network Drive” and enter one of the following UNC paths depending on which location on Midway you wish to connect to:  

=== "Midway2, DaLI"
    === "Home"
        ```
        \\midwaysmb.rcc.uchicago.edu\homes
        ```
    ===+ "Project2"
        ```
        \\midwaysmb.rcc.uchicago.edu\project2
        ```
    === "Scratch"
        ```
        \\midwaysmb.rcc.uchicago.edu\midway2-scratch
        ```
    === "CDS"
        ```
        \\midwaysmb.rcc.uchicago.edu\cds
        ```
        !!! Note
            CDS storage can be mapped via Samba only upon the PI's request.
    === "CDS2"
        ```
        \\midwaysmb.rcc.uchicago.edu\cds2
        ```
        !!! Note
            CDS2 storage can be mapped via Samba only upon the PI's request.
===+ "Midway3, Midway3-AMD, MidwaySSD"
    === "Home"
        ```
        \\midway3smb1.rcc.uchicago.edu\homes
        ``` 
    ===+ "Project"
        ```
        \\midway3smb1.rcc.uchicago.edu\project
        ```
    === "Scratch"
        ```
        \\midway3smb1.rcc.uchicago.edu\midway3-scratch
        ```
    === "CDS3"
        ```
        \\midway3smb1.rcc.uchicago.edu\cds3
        ```
=== "Beagle3"
    === "Home (Midway3 Mirror)"
        ```
        \\midway3smb1.rcc.uchicago.edu\homes
        ``` 
    ===+ "Project"
        ```
        \\midway3smb1.rcc.uchicago.edu\beagle3
        ```
    === "Scratch"
        ```
        \\midway3smb1.rcc.uchicago.edu\beagle3-scratch
        ```
    === "CDS3"
        ```
        \\midway3smb1.rcc.uchicago.edu\cds3
        ```

Enter **``ADLOCAL\CNetID``** for the username and enter your CNetID password.  

![Map Network Drive](../../img/data_management/map_network_drive.png)

## Connecting from macOS   


On a macOS computer, select “Connect to Server” (from the "Go" menu in Finder) and enter one of the following URLs depending on which location on Midway you wish to connect to:  

=== "Midway2, DaLI"
    === "Home"
        ```
        smb://midwaysmb.rcc.uchicago.edu/homes
        ```
    ===+ "Project2"
        ```
        smb://midwaysmb.rcc.uchicago.edu/project2
        ```
    === "Scratch"
        ```
        smb://midwaysmb.rcc.uchicago.edu/midway2-scratch
        ```
    === "CDS"
        ```
        smb://midwaysmb.rcc.uchicago.edu/cds
        ```
        !!! Note
            CDS storage can be mapped via Samba only upon the PI's request.
    === "CDS2"
        ```
        smb://midwaysmb.rcc.uchicago.edu/cds2
        ```
        !!! Note
            CDS2 storage can be mapped via Samba only upon the PI's request.
===+ "Midway3, Midway3-AMD, MidwaySSD"
    === "Home"
        ```
        smb://midway3smb1.rcc.uchicago.edu/homes
        ``` 
    ===+ "Project"
        ```
        smb://midway3smb1.rcc.uchicago.edu/project
        ```
    === "Scratch"
        ```
        smb://midway3smb1.rcc.uchicago.edu/midway3-scratch
        ```
    === "CDS3"
        ```
        smb://midway3smb1.rcc.uchicago.edu/cds3
        ```
=== "Beagle3"
    === "Home (Midway3 Mirror)"
        ```
        smb://midway3smb1.rcc.uchicago.edu/homes
        ``` 
    ===+ "Project"
        ```
        smb://midway3smb1.rcc.uchicago.edu/beagle3
        ```
    === "Scratch"
        ```
        smb://midway3smb1.rcc.uchicago.edu/beagle3-scratch
        ```
    === "CDS3"
        ```
        smb://midway3smb1.rcc.uchicago.edu/cds3
        ```

Enter **``ADLOCAL\CNetID``** for the username and enter your CNetID password.  


![Connect to Server](../../img/data_management/connect_to_server.jpg)  

