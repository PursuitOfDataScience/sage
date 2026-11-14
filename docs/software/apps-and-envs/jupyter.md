# Jupyter

Jupyter Notebook is a popular tool for Python users that provides interactive, web-based computing. JupyterLab is its next-generation IDE-like counterpart, offering more advanced features for data science, scientific computing, computational journalism, and machine learning. Its modular interface lets you create and run multiple documents in separate tabs within the same window.

For lightweight work, you can launch Jupyter on a login node and access its interface from your local machine while all computation runs on Midway. Note that login node resources are shared among all users, and no dedicated hardware such as large RAM or GPUs is available. For heavy computation, request resources through an interactive or batch job before launching Jupyter.

## Jupyter on Login Nodes
### IDE
If you connect to Midway from an IDE such as VSCode using its Remote-SSH extension, you can open and run Jupyter notebooks directly in the editor without starting a server or setting up a tunnel. Open a `.ipynb` file, click **Select Kernel**, and choose the Python environment you prepared in Step 1 of the [Terminal](#terminal) section. The environment must include `ipykernel`. The notebook kernel runs on the login node you are connected to, so the same resource limits apply.

!!! note
    The Jupyter extension must be installed on the remote host, even if it is already installed in your local IDE. Extensions installed locally do not run on Midway. In VSCode, open the Extensions view while connected to Midway, find **Jupyter**, and click **Install in SSH: midway3...**.

### Terminal
Connect to a Midway login node, then follow these steps:

**Step 1**: Load a Python module and activate a Python virtual environment that has the `ipykernel` package installed. If you have not created one yet, follow the steps in the Python article of this manual.

**Step 2**: Launch the Jupyter server. Set the `HOST_IP` and `PORT_NUM` variables. `HOST_IP` is the IP address of the login node, and `PORT_NUM` is a free port that Jupyter will listen on:

```
HOST_IP=`/sbin/ip route get 8.8.8.8 | awk '{print $7;exit}'`
echo "HOST_IP=$HOST_IP"
PORT_NUM=$(shuf -i15001-30000 -n1)
echo "PORT_NUM=$PORT_NUM"
```

Then launch the Jupyter Notebook server:

```
jupyter-notebook --no-browser --ip=$HOST_IP --port=$PORT_NUM
```

This will print two URLs containing a token: one with the external address `128.135.x.y` and another with the localhost address `127.0.0.1`. The on-campus address `10.50.x.y` is also shown if you are connected via VPN. The URLs look like:

```default
http://128.135.167.77:15021/?token=9c9b7fb3885a5b6896c959c8a945773b8860c6e2e0bad629
http://127.0.0.1:15021/?token=9c9b7fb3885a5b6896c959c8a945773b8860c6e2e0bad629
```

The on-campus address `10.50.x.y` is accessible only when connecting to Midway2 or Midway3 via VPN.

**Step 3**: Set up an SSH tunnel from your local machine to the login node. Open a local terminal and run the command below, replacing the variables with the values echoed in Step 2. Use the value of `HOST_IP`, not the login node's hostname (such as `midway3-login3`). Inside the cluster, the hostname resolves to the node's internal interface, but Jupyter is listening on the external interface given by `HOST_IP`:

```
ssh -N -L PORT_NUM:HOST_IP:PORT_NUM CNETID@midway3.rcc.uchicago.edu
```

**Step 4**: Open a browser on your local machine and paste the localhost URL with the token printed by the Jupyter server (`http://127.0.0.1:.../?token=...`) into the address bar.

**Step 5**: To stop Jupyter, return to the terminal where it is running and press `Ctrl+C`, then confirm with `y`.


## Jupyter on Compute Nodes
### Open OnDemand
Open OnDemand is the simplest way to run Jupyter on a compute node. Log in to the [Midway3 Open OnDemand portal](https://midway3-ondemand.rcc.uchicago.edu) in your browser (on-campus network or VPN required; see [Open OnDemand](../../connection/open_ondemand/open_ondemand.md) for details) and select the Jupyter app. You will see a form where you point to the Python environment you have already configured (it must include `ipykernel`) and request resources. You can choose the account, partition, number of cores, memory, wall time, and GPUs from the options available to you.

When you submit the form, Open OnDemand starts a Slurm job and launches the Jupyter server on the assigned compute node. Once the job starts, a **Connect** button appears, and clicking it opens JupyterLab in your browser.

You do not need a batch script, an SSH tunnel, or a token URL. Open OnDemand handles the connection between your browser and the compute node for you. The session runs until the requested wall time expires or you delete it from the **My Interactive Sessions** page. Closing the browser tab does not stop the job.

### Terminal 
When Jupyter runs on a compute node, it returns an on-campus URL (`10.50.x.y`) rather than an external address (`128.135.x.y`). An SSH tunnel is required to reach it from outside the cluster network.

**Step 1**: Write a batch script, `jupyter_on_compute.sh`, replacing `[pi-account]` with the PI account to charge for SUs and adjusting the requested resources as needed. On Midway2, change the `CLUSTER` variable to `midway2.rcc.uchicago.edu` and update the Python module name accordingly. Make sure the activated environment includes `ipykernel` and its dependencies.

```
#!/bin/bash
#SBATCH --job-name=jupy-job
#SBATCH --output=jupy-%J.out
#SBATCH --error=jupy-%J.err
#SBATCH --account=[pi-account]
#SBATCH --time=04:00:00
#SBATCH --partition=caslake
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --mem=4GB

module load python/miniforge-25.3.0
source activate base

cd $SLURM_SUBMIT_DIR

HOST_IP=`/sbin/ip route get 8.8.8.8 | awk '{print $7;exit}'`
PORT_NUM=$(python3 -c "import socket; s=socket.socket(); s.bind(('', 0)); print(s.getsockname()[1]); s.close()")
NODE=$(hostname -s)
USER=$(whoami)
CLUSTER='midway3.rcc.uchicago.edu'

echo "ssh -N -L $PORT_NUM:$NODE:$PORT_NUM $USER@$CLUSTER"

jupyter lab --no-browser --ip=$HOST_IP --port=$PORT_NUM
```

**Step 2**: Submit the batch job and verify that it is running:

```
sbatch jupyter_on_compute.sh
squeue --format="%.18i %.9P %c %.30j %.8u %.8T %.10M %.9l %.6D %R" --me
```

Once the job is running, open `jupy-[JobID].out` to find the SSH tunnel command printed by the script.

**Step 3**: Set up an SSH tunnel from your local machine to the compute node. Open `jupy-[JobID].out`, copy the tunnel command, then run it in a local terminal (PowerShell, MobaXterm, Terminus, etc.). It will look like this, with the port number and node name filled in by the job:

```
ssh -N -L 52915:midway3-0008:52915 cnetid@midway3.rcc.uchicago.edu
```

You will be prompted for your password and two-factor authentication. Once authenticated, the terminal will appear to hang — this is expected. The tunnel runs as a foreground process and must stay open while you use Jupyter. Do not close that terminal window.

**Step 4**: Connect to the Jupyter server. Open `jupy-[JobID].err` and copy the URL starting with `http://127.0.0.1:.../?token=...`. Paste it into your browser's address bar. Some Jupyter extensions may generate error messages in this file because the air-gapped compute nodes cannot access the internet.

!!! note
    If you are viewing the `.err` file in VSCode with automatic port forwarding enabled, do not click the link. Clicking it will fail because VSCode forwards ports from the login node, not from the compute node where Jupyter is running. Either disable automatic port forwarding in VSCode settings (`"remote.autoForwardPorts": false`) or copy and paste the URL manually.

**Step 5**: To stop Jupyter, run `scancel [JobID]`. Closing the tunnel terminal only drops your local connection; the Jupyter server continues running on the compute node until the job is cancelled.