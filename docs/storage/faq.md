# Data Management FAQ

### How much storage space do I have left/used?
Keep track of your storage usage by logging into Midway clusters and running the `quota` command. This handy tool on the Midway2 and Midway3 ecosystems provides you with all the corresponding information you need.

### I'm over quota (expired quota); what do I do?
If you find yourself over quota (expired quota), fret not! Follow these steps to get back on track:

Identify whether your quota is expired due to the number of files (`files`) or total file size (`blocks`). If it's due to the number of files, consider zipping some files to count as one, rather than a large set of small files. If your quota is expired due to file size:

1. If `/home` is expired, move your files to `/scratch` or `/project/drpepper`. Some users may also utilize `/dali/drpepper`, `/beagle3/drpepper`, `/cds/drpepper`, `/cds2/drpepper`, or `/cds3/drpepper`.
2. If `/scratch` is expired, relocate your files to `/project/drpepper`. Similarly, some users may utilize `/dali/drpepper`, `/beagle3/drpepper`, `/cds/drpepper`, `/cds2/drpepper`, or `/cds3/drpepper`. Alternatively, delete unnecessary files.
3. Request your PI to submit a research allocation request to [obtain more storage](https://rcc.uchicago.edu/accounts-allocations/request-allocation). If the standard research allocation is insufficient, consider supplemental research allocation for temporary storage expansion.
4. Ask your PI to purchase additional storage via the [cluster partnership program](https://rcc.uchicago.edu/support-and-services/cluster-partnership-program).

### Why can't I write files into my home directory?
Encountering errors while writing files typically indicates that you're over quota. Ensure that you're within quota limits in terms of both size and number of files using the `quota` command.

### How do I increase my storage quota?
Expand your storage capacity through the [Cluster Partnership Program](https://rcc.uchicago.edu/support-and-services/cluster-partnership-program). Alternatively, request additional storage as part of a [Research II Allocation or Special Allocation](https://rcc.uchicago.edu/accounts-allocations/request-allocation).

### How do I share files with others?
**Option 1: Globus**
See [Share Files with Globus](../data_sharing/globus_sharing.md) for details on file sharing via Globus.

**Option 2: Advanced access control via ACL**
Refer to [Advanced Access Control via ACL](../data_sharing/access_control.md#advanced-access-control-via-acl) for detailed instructions.

**Option 3: Allow them to join your RCC group**
Direct individuals to fill out the [general user account request form](https://rcc.uchicago.edu/accounts-allocations/general-user-account-request){:target='_blank'} for group access. Keep in mind that this grants access to all your `/project` files and compute resources, making it an all-encompassing choice for file sharing.

### I accidentally deleted or lost a file. How do I restore it?
The most effective method for file recovery is to use snapshots. See [Snapshots](main.md#snapshots) for details.

### Unlocking access to files under `/project` for departed users

Have you stumbled upon files in `/project` belonging to a former UChicago member? No worries! We've got you covered. Simply shoot us an email at [help@rcc.uchicago.edu](mailto:help@rcc.uchicago.edu) with the precise path to the directories in question. Don't forget to include the PI's information for approval. We'll handle the rest and get you access in no time! 