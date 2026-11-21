# Allocations and Service Units FAQ

## What is an allocation?
An allocation is a system designed to ensure fair usage of computing resources (service units) and storage (gigabytes) granted to a Principal Investigator (PI) or an education account.

### Service Units (SUs)
In simple terms, you consume service units as you run jobs on shared compute nodes. Applying for service units incurs no cost for PIs and is solely a means to ensure fair usage of shared compute nodes. Please refer to [RCC Allocations](https://rcc.uchicago.edu/accounts-allocations/allocation-service-units) for more detailed information. Note that certain nodes or partitions, such as those in the Cluster Partnership Program, as well as private nodes and partitions like Beagle3 and MidwaySSD, do not consume service units when utilized since they are not shared resources. 

### Storage
RCC offers a limited volume of free group share storage alongside service units when a PI applies for an allocation. If you require additional storage space beyond what is allocated, please contact our CPP team at [cpp@rcc.uchicago.edu](mailto:cpp@rcc.uchicago.edu).

## What is a service unit (SU)?
As you execute jobs on shared compute nodes at RCC, you deplete service units, akin to utilizing fuel. By imposing a cap on the number of service units that can be consumed per academic year, we ensure equitable utilization of our shared compute nodes. For a more precise definition, please visit [RCC Service Units](https://rcc.uchicago.edu/accounts-allocations/user-guidelines).

## How do I obtain an allocation?
For detailed information on obtaining an allocation, please refer to [RCC Allocations](https://rcc.uchicago.edu/accounts-allocations/allocation-service-units).

## How does RCC calculate the service units used for running a job on shared nodes?
For insights into how RCC calculates the service units expended during job execution on shared nodes, please consult [RCC Allocations](https://rcc.uchicago.edu/accounts-allocations/calculations-service-units).

## How do I check how many service units I have remaining on my allocation?
The `accounts` tool offers a convenient means to check your account balance. Simply log into RCC clusters via `ssh` and execute the following command:

``` 
accounts balance  
```

You can also log into your [MyRCC](https://my.rcc.uchicago.edu/overview) profile and check the service units of the accounts you are a member of in a user-friendly web interface.

## How do I review the usage of my allocation?

The `accounts` tool provides several options for summarizing the usage of the allocations to which your RCC account has access. To obtain a summary, execute the command `accounts usage` with the account name(s):


=== "Midway2, DaLI"
      ```
      accounts usage
      accounts usage --account [pi-cnetid]
      accounts usage --accounts [pi-cnetid1],[pi-cnetid2]
      ```
      
===+ "Midway3, Beagle3"
      ```
      accounts usage
      accounts usage -a [pi-cnetid]
      ```

where `[pi-cnetid]` is the name of the account, often your PI's.

You may use the `--byuser` option to view individual usage by group members:

=== "Midway2, DaLI"
      ```
      accounts usage
      accounts usage --account [pi-cnetid] --byuser
      ```

===+ "Midway3, Beagle3"
      ```
      accounts usage
      accounts usage -a [pi-cnetid] -byuser
      ```

You can also use the `rcchelp` command (a wrapper of system-provided tools including `accounts`), which requires slightly different arguments (note the single dash `-`):

=== "Midway2, DaLI"
      ```
      rcchelp usage 
      rcchelp usage -account [pi-cnetid] -byuser
      ```

=== "Midway3, Beagle3"
      ```
      rcchelp usage 
      rcchelp usage -a [pi-cnetid] -byuser
      ```

---

To view the resource usage per job, you need to run on Midway2/DaLI using either `accounts`:

=== "Midway2, DaLI"
      ```
      accounts usage --byjob
      accounts usage --account [pi-cnetid] --byjob
      ```

or `rcchelp`:

=== "Midway2, DaLI"
      ```
      rcchelp usage -byjob
      rcchelp usage -account [pi-cnetid] -byjob
      ```

Both include jobs on Midway2 and Midway3 partitions (e.g., `caslake` and `gpu`). 

!!!note 
     These commands, although executed on the Midway2 ecosystem, provide the necessary information about jobs run on both Midway2 and Midway3.

The output is a table that lists the job IDs, partitions, number of CPU cores, and SU consumption. To further check the resource consumption of a job on Midway3, you need to log in to Midway3 and run `sacct -j` with the job ID. 

If the job is still running, you can use `scontrol show job` with the job ID to check the job information.

---

*For additional details on account creation, visit the [accounts and allocations page](https://rcc.uchicago.edu/accounts-allocations) on our main website.*