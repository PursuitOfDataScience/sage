# Welcome to Open OnDemand at RCC UChicago

## Introduction

Open OnDemand (OOD) is a web-based portal that provides seamless, user-friendly access to High-Performance Computing (HPC). With OOD, you can manage files, submit and monitor jobs, and launch interactive applications such as Jupyter, RStudio, and graphical desktop sessions — all from your web browser directly to the compute nodes, without needing to use the command line.

## Accessing Open OnDemand at the RCC

To access the RCC Open OnDemand service:

1.  Open your favorite web browser (Chrome, Firefox, Safari, or Edge are recommended).
2.  Navigate to [https://midway3-ondemand.rcc.uchicago.edu](https://midway3-ondemand.rcc.uchicago.edu) using on-campus networks or [cVPN](https://uchicago.service-now.com/esc/escservices@uchicago.edu?id=kb_article&sys_id=9f963146330f2a9080866cdfcd5c7b68&spa=1).
3.  You will be prompted to log in with your CNetID and password.

![Open OnDemand login screen with CNetID and password fields](images/login_ondemand_screen.jpeg)
<div class="caption">Figure 1: Login screen</div>


## Open OnDemand Dashboard

After logging in, you will see the Open OnDemand dashboard (Figure 2). This is your main portal for accessing HPC resources.

![OOD Dashboard showing commonly used apps](images/dashboard_commonly_used_apps.png)
<div class="caption">Figure 2: OOD Dashboard showing commonly used apps</div>

The entries in the top bar menu include:

* **Apps**: Shows the commonly used apps.

* **Files**: Manage files and folders in your home directory and other accessible storage locations on Midway. You can upload, download, copy, move, rename, and delete files and folders.

  ![OOD File Manager with Upload dialog](images/file_manager_upload.jpg)
  <div class="caption">Figure 3: OOD File Manager with Upload dialog</div>

* **Jobs**:
    * **Active Jobs**: View and manage your currently running and queued jobs on the Slurm scheduler.
    * **Job Composer**: Create and submit new batch jobs using predefined templates or by writing your own submission scripts.

      ![OOD Job Composer interface](images/job_composer_overview.png)
      <div class="caption">Figure 4: OOD Job Composer user interface</div>

      ![OOD Job Composer showing job details and script contents](images/job_composer_job_details.png)
      <div class="caption">Figure 5: OOD Job Composer showing job details and script contents</div>

* **Clusters**: Get shell (terminal) access to the Midway3 cluster directly from your browser.

* **Interactive Apps**: Launch interactive graphical applications or server-based applications like Jupyter Notebooks, RStudio Server, and full Linux Desktop environments.


## Typical Workflow

1.  **Manage Files:** Use the Files app to upload data, organize directories, and edit scripts.
2.  **Submit Jobs:** Request resources to run the interactive applications, either by filling in the app form or by using the Job Composer app.
3.  **Launch Interactive Apps:** Start a Jupyter Notebook, RStudio Server, or a full Linux desktop session on the compute node in a new tab of your web browser. You can close the tab and resume the session by clicking the button ``Launch [AppName]`` or ``Connect to [ServerName]`` in the Job card.
4.  **Monitor and Manage:** Track your jobs and sessions, and clean up resources when finished. Manage your research projects, potentially including data and job organization.

## Using Interactive Apps

One of the most powerful features of Open OnDemand is the ability to launch interactive applications that run on the compute nodes of the Midway3 cluster.

**General Steps to Launch an Interactive App:**

1.  From the OOD dashboard, click on "Interactive Apps" in the top menu.

    ![OOD Interactive Apps Dropdown Menu](images/interactive_apps_menu.png)
    <div class="caption">Figure 6: OOD Interactive Apps Dropdown Menu</div>

2.  A dropdown list of available applications will appear (e.g., Midway3 Desktop, Jupyter Server, RStudio Server).
3.  Select the application you wish to use.
4.  You will be presented with a form (Figure 7) to specify the resources for your session:
    * **Account**: Your Slurm account/allocation (if applicable).
    * **Partition**: The Slurm partition to run the job on.
    * **Number of hours**: How long you need the session.
    * **Number of cores**: The number of CPU cores requested.
    * **Memory**: The amount of memory (RAM) required.
    * Other application-specific options may also be available.
    ![Job Form](images/job_form.png)
    <div class="caption">Figure 7: Job form to request resources for running the app</div>
5.  Once you have filled out the form, click ``Launch``.
6.  Your job will be submitted to the Slurm scheduler. You will see its status in the "My Interactive Sessions" section of the dashboard.
7.  When the job starts and resources are allocated, which may take some time depending on the cluster load and your recent usage history, a Job card (Figure 8) will appear with the ``Host`` field showing the compute node where your session is running. Click on the button ``Connect`` or ``Launch`` to open your interactive session in a new browser tab.
    ![Job Card](images/job_card.png)
    <div class="caption">Figure 8: Job card showing the running app with Host and Session ID with a link to the location where the log files of the session are stored.</div>
8.  When you are finished with your session, explicitly **close the application and then delete your interactive session** from the "My Interactive Sessions" page to free up resources.


## Managing Your Sessions and Files
* **Interactive Sessions**: Always remember to explicitly **delete** your interactive sessions from the "My Interactive Sessions" page when you are finished. Simply closing the browser tab does NOT terminate the job on the cluster.
* **File Management**: Be mindful of your storage quotas. Data generated within Open OnDemand sessions is stored in your standard RCC home or project directories.



