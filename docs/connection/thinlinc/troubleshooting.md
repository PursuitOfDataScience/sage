
# ThinLinc - Troubleshooting

## ThinLinc client 

When logging into the ThinLinc app, click `end existing session`. This will terminate other open sessions. 

## Check your account quota

If you have too many files in your home directory on Midway clusters with an `expired quota` flag, then ThinLinc cannot write its cache files upon login, which can result in having trouble with login through ThinLinc. To check your account `quota` or, in other words, the status of how much space files in your home directory are taking and how many files you have, log into `Midway3` (or `Midway3-AMD` or `MidwaySSD` or `Beagle3`) through SSH and then type in `quota` and then press enter if there is an `expired` on any of your home directories. 

An example output of `quota` command: 

```
---------------------------------------------------------------------------
fileset          type                   used      quota      limit    grace
---------------- ---------------- ---------- ---------- ---------- --------
Midway2 home     blocks (user)         2.30G     30.00G     35.00G     none
                 files  (user)        300100     300000    1000000  expired
Midway3 home     blocks (user)       768.94M     30.00G     35.00G     none
                 files  (user)         21274     300000    1000000     none
scratch/midway2  blocks (user)         0.00K    100.00G      5.00T     none
                 files  (user)             1   10000000   20000000     none
scratch/midway3  blocks (user)         0.00K    100.00G      2.00T     none
                 files  (user)             1   10000000   20000000     none
---------------- ---------------- ---------- ---------- ---------- --------
>>> Capacity Filesystem: project (Midway3 GPFS)
---------------- ---------------- ---------- ---------- ---------- --------
pi-drpepper      blocks (group)      111.44T    300.00T    301.00T     none
                 files  (group)     34821665  230900000  231900000     none
---------------- ---------------- ---------- ---------- ---------- --------
>>> Capacity Filesystem: project2 (Midway2 GPFS)
---------------- ---------------- ---------- ---------- ---------- --------
pi-drpepper      blocks (group)      317.06T    500.49T    501.49T     none
                 files  (group)     52948203  384875000  385875000     none
---------------------------------------------------------------------------
```

In this example, the `expired` flag on `Midway2 home` means the user has too many files. After removing or moving some of the files from `Midway2 home` to `scratch/midway2` or `project2` directories, the issue will be resolved after our system reviews the accounts' quota again in a few hours. 

## Cleaning cache files and closing unfinished sessions

Sometimes, ThinLinc leaves some cache files from previous sessions that can cause issues. To close the unfinished sessions, log into the cluster through SSH and run the following command: 

```
kill -9 `ps -ef|grep thin|grep $USER|awk '{print $2}'|paste -d " " -s`
```

This might give the following error, but you can ignore it and try to log in through ThinLinc again. 

```
-bash: kill: (2601223) - No such process
```

To clean cache files, log in through SSH and go to your home directory: 
 
```
cd $HOME
``` 

Then remove the cache files: 

```
rm -rf .cache/* .config/* .dbus/*
```

And also, `.local/share` files: 

```
cd .local/share
```
Then: 

```
rm -rf gnome-* nautilus
```

If the issue persists, let us know by contacting our helpdesk. 

## Conflict with `conda` files 
Log into the Midway cluster through SSH and then open `~/.bashrc` file. 

``` 
vim ~/.bashrc
```


If there is anything related to the conda environment, please delete that. This would be any line in between:

```
# >>> conda initialize >>>
Hide quoted text
# !! Contents within this block are managed by 'conda init' !!
............
and
unset __conda_setup
Show quoted text

```

Sometime it appears as: 

```
__conda_setup="$('/software/python-anaconda-2020.02-el7-x86_64/bin/conda' 'shell.bash' 'hook' 2> /dev/null)"
if [ $? -eq 0 ]; then
eval "$__conda_setup"
else
if [ -f "/software/python-anaconda-2020.02-el7-x86_64/etc/profile.d/conda.sh" ]; then
. "/software/python-anaconda-2020.02-el7-x86_64/etc/profile.d/conda.sh"
else
export PATH="/software/python-anaconda-2020.02-el7-x86_64/bin:$PATH"
fi
fi
unset __conda_setup
```


