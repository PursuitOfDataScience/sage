# Transfer Files with Globus

**Globus** is a robust file-sharing and transfer service. Globus calls a collection of files an endpoint. The RCC has several Globus endpoints. This guide explains how to make your computer a Globus endpoint and transfer files between Globus endpoints. Put another way, this guide explains how to move files between your local system (i.e., your computer, lab computers, etc.) and the RCC's Midway2 and Midway3 ecosystems. 

Note that this guide focuses on transferring files through the <a href='https://globus.rcc.uchicago.edu/' target='_blank'>Globus web app</a>. Advanced users can access additional functionality by using the
<a href='https://docs.globus.org/cli/' target='_blank'>Globus command line interface (CLI)</a>, a standalone app that you can install on your computer and then use to access Globus.

## Make Your Computer a Globus Endpoint

Follow the instructions in the <a href='https://docs.globus.org/globus-connect-personal/install/' target='_blank'>Globus documentation</a> to install Globus Connect Personal and make your computer a Globus endpoint (also called a collection). When Globus Connect Personal asks you to authenticate (Step 4), log in with your UChicago CNetID. 

Once your computer is a Globus endpoint, you will be able to access files stored on your local system, as well as files stored in the RCC's ecosystems, from <a href='https://globus.rcc.uchicago.edu/' target='_blank'>globus.rcc.uchicago.edu</a>. To access your locally stored files, click "File Manager" in the toolbar on the left of your screen and type the name you gave your personal endpoint into the collection search bar: 

<p align='center'>
<img src='/img/globus/personal-endpoint.png'
width='650'
alt='Globus web app open to the File Manager section. "Your Personal Endpoint Name" is typed into the collection search bar.'/>
</p>

## Manually Transfer Files

To see files in different collections at the same time, click the "two panes" icon next to "Panels" in the upper-right corner:

<p align='center'>
<img src='/img/globus/two-panes.png'
width='650'
alt='Globus web app File Manager open in two-pane mode.'/>
</p>

To transfer files between collections, open the source directory (where the files are currently) in one pane of the File Manager and the destination directory (where you want to move the files) in the other. Select the files you want to transfer from the source directory and drag and drop them into the destination directory or click the blue "Start" button above the source directory:

<p align='center'>
<img src='/img/globus/manual-transfer.png'
width='650'
alt='Globus web app File Manager open in two-pane mode with the "Start" button highlighted.'/>
</p>

You can customize your transfer with the "Transfer & Timer Options" drop-down menu at the center top of your screen. You can also use this menu to schedule transfers (see below). Advanced users can access additional file transfer functionality by using the <a href='https://docs.globus.org/cli/' target='_blank'>Globus command line interface (CLI)</a>.

## Schedule a File Transfer

To schedule a one-time or recurring file transfer, open the File Manager with your source directory in one pane and your destination directory in the other, as you would for a manual file transfer (see above). Select the files you want to transfer in the source directory, then click "Transfer & Timer Options" at the center top of your screen:

<p align='center'>
<img src='/img/globus/auto-transfer.png'
width='650'
alt='Globus web app File Manager open in two-pane mode with the "Transfer & Timer Options" highlighted.'/>
</p>

Specify the date and time you would like your transfer to occur with the "Schedule Start" option at the bottom of the menu. If you are scheduling a recurring transfer, this will be the date and time of the first occurrence. Use MM/DD/YYYY for the date and 12-hour time. For example, 12/15/2023, 1:30 PM:

<p align='center'>
<img src='/img/globus/schedule-start.png'
width='650'
alt='"Schedule Start" option set to 12/15/2023 1:30 PM.'/>
</p>

Use the "Repeat" option at the bottom of the menu to schedule a recurring file transfer. Specify how frequently you would like the transfer to occur and, optionally, when you would like the transfer to stop. For example, you could schedule a transfer to happen every other day for a year:

<p align='center'>
<img src='/img/globus/recurring-transfer.png'
width='650'
alt='A recurring file transfer. "Repeat" is set to "days", "every" is set to 2 days, and the end is set to by date 12/15/2024, 01:30 PM.'/>
</p>

## Globus Flows
You can also transfer files (<a href='https://docs.globus.org/api/flows/hosted-action-providers/' target='_blank'>and more!</a>) with Globus Flows, which offers a way to set up automated, reusable, and sharable workflows. This is a *brief* overview of Globus Flows. For a comprehensive guide to the service, including detailed examples, see the <a href='https://docs.globus.org/api/flows/' target='_blank'>Globus Flows documentation</a>.

**Think of a flow like a function:** you run a flow when you want something to happen on Globus, just like you call a function when you want something to happen in your code. Globus offers <a href='https://docs.globus.org/api/flows/#getting_started' target='_blank'>two ready-made flows</a>:

* The **Move (Copy and Delete)** flow copies data between collections and then deletes the original data from the source collection.

* The **Two-Stage Transfer** flow copies data between two collections using a third collection as an intermediate location, which can be useful for meeting security and compliance requirements.


You can also run flows other Globus users have created, just like you can call functions from different libraries, or create custom flows, just like you can define your own functions.

**To work with Globus Flows, go to the Flows section of the <a href='https://globus.rcc.uchicago.edu/' target='_blank'>Globus Web App</a>.** The first time you click into the Flows section, you will need to give Globus permission to manage flows on your account:

<p align='center'>
<img src='/img/globus/flows-section.png'
width='650'
alt='Globus Web App with the Flows section at the bottom of the sidebar menu highlighted.'/>
</p>

<p align='center'>
<img src='/img/globus/allow-flows.png'
width='650'
alt='Web page titled "University of Chicago RCC Globus Web App would like to Manage Flows" with "Allow" highlighted.'/>
</p>

When you click "Allow," Globus will route you to the Runs tab of the Flows section:

<p align='center'>
<img src='/img/globus/flows-runs.png'
width='650'
alt='Globus Flows open to the Runs tab. Flow runs that you have started or can monitor will be listed here. Visit the Library tab to find flows to run.'/>
</p> 

A full list of flows you can view or use is available in the Library tab. Use the search bar at the top of the page to search for flows and/or the filters in the top-right corner to narrow down your options:

<p align='center'>
<img src='/img/globus/flows-library.png'
width='650'
alt='Globus Flows open to the Library tab with search bar and filters at the top of the page highlighted.'/>
</p>

Steps for creating additional, custom flows are listed in the Deploy a Flow tab:

<p align='center'>
<img src='/img/globus/flows-deploy.png'
width='650'
alt='Globus Flows open to the Deploy a Flow tab.'/>
</p>

