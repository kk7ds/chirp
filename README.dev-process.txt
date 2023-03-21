Chirp ReadMe Dev Process
Dave Liske, KE8WDM

Introduction: 
A)  This README is intended for beginners to Chirp development and/or Github newbies.

B)  While there may be some variations of the following procedure(s), this is the most basic path to using Github 
to assist in the development of Chirp and its drivers. Understand that Chirp's testing of new files via TOX is 
rather strict, and Chirp's longtime developers hold themselves and the software to a similarly strict standard. 
In doing so, they're doing what they feel is best for their users. Respond to them accordingly, and in as polite 
a manner as possible.

===================================

1)	The Chirp PR checklist states "Major new features or bug fixes should reference a CHIRP issue." If such an
    issue does not yet exist at https://chirp.danplanet.com/projects/chirp/issues for what you need to code,
    create a Chirp Support account or log in, and follow the instructions to open a new issue. 
2)  Subscribe to the chirp_devel email list at http://intrepid.danplanet.com/mailman/listinfo/chirp_devel.
3)	Install a suitable Python editor.
4)	Create a Github account at github.com.
5)	Install Git from https://github.com/git-guides/install-git

    5a)	When installing Git, for the line ending conversions choose "Checkout as-is, commit Unix-style line 
        endings". Windows uses a CRLF (DOS) line ending format, but Chirp tests requires the LF (UNIX) format
		
6)	Create a fork of Chirp from https://github.com/kk7ds/chirp into your own Github account, as a Master repository.
7)  In your repository of Chirp, click the Branches tab.
8)  Click the New Branch button and give your topic branch a name, including the issue number as "#xxxx".
    
    8a)     Name your branch something consistent with the issue, i.e., "add-readme-dev-process."
    8b)     You'll be putting your changes into a Topic Branch, NOT a Master Branch. Using your own Master makes it
    more difficult for Chirp's developers to pull, fix, and re-push commits for you.
	
9)	Copy the desired file to your machine or, opening a new file, use your Python code editor to update or create
    the driver. 
	
    9a) Driver/Module Formatting Rules:
        1)  If updating or adding to a current driver, the file name must be the same as the file in 
            documents/github/chirp/chirp/drivers.
        2)  Line indents are 4 spaces each, not tabs.
        3)  Lines cannot be more than 80 characters in length.
        4)  Line continuations should be indented visually, aligned with the beginning of the same section of code 
            in the first line, inside that line’s open parentheses or bracket (directly under the first character). 
            Any further line continuations following this may either do the same, or be indented 4 spaces, i.e.:
            
			===================================
		    group.append(
                RadioSetting(key, title,
                             RadioSettingValueList(
                                 choices,
                                 choices[val])))
		    ===================================
			
            (Note: Not doing this correctly is the cause for “over-indent” and “under-indent” errors during 
            testing.)
        5)  Add no extraneous whitespace.
        6)  There should be 2 spaces between code and inline comments.
        7)  Empty lines must not have whitespaces.
        8)  Code and comment lines must not have trailing whitespaces.
        9)  There must be two hard returns between sections (before and after classes, etc.)
        10) The last line in the file MUST be a hard return with no trailing whitespaces. Some editors such as 
	        Notepad++ will add an indent, which must be backspaced.
			
10) Use Chirp to test your code against the radio(s):

    10a)    Connect a programming cable between the ham radio and your machine’s USB port. Any cable with the 
            Kenwood style 2-pin plug should work, but it should be one with an FTDI type USB-to-Serial chip.
            Most online ham radio dealers offer this cable.
    10b)    Open Chirp and click “Help | Developer Mode.” This menu item will become checked as Active.
    10c)    Click “File | Load Module.” You will see a warning message, which you should read.
    10d)    Once the Open dialog box appears, point it to your file and click “Open.”
    10e)    Back in Chirp, if there are no obvious Python errors, click “Radio | Download from radio.”
    10f)    Be sure your USB port and the necessary radio Vendor and Model are selected.
    10g)    Click Download. If all is well, the data will download from the radio.
	
11)	Once your code is complete and tests well against the hardware, IF adding radio models or families to drivers, 
    save an IMG file from Chirp’s “Save As” menu item using the naming format of “vendor_model.img”, which is the 
    same as the suggested IMG file name without the included date.
	
    11a)    Note: If you are NOT adding models or families, DO NOT create a replacement IMG file.

12)	In Github, upload the driver file into /chirp/chirp/drivers in your topic branch.

    12a)    In your topic branch, click "Add File | Upload Files".
	12b)    Upload the file(s).
	12c)    Under "Commit Changes" add a subject line that includes the issue number, i.e.,
            "Add README-dev-process - fixes #10463".
	12d)    Add a slightly-longer description, while still being quite succinct
	
13)	If an IMG file is needed for added radios or radio families, in Github, copy-and-paste the file into 
    /chirp/tests/images in your topic branch.
    
    13a)    Follow the same procedure as begins in (12a)
	
14) When all files have been uploaded, click the green "Compare & Pull Request" button.
15)	Follow the instructions on the "Open a Pull Request" page.

16)	Once your pull request is submitted, watch your email for the results of TOX tests against your files.
17)	All Pull Requests must fulfill the following checklists:
    
	===================================
    o	CHIRP PR Checklist
    o	The following must be true before PRs can be merged:

        o	All tests must be passing.
        o	Commits should be squashed into logical units.
        o	Commits should be rebased (or simply rebase-able in the web UI) on current master. Do not put merge 
            commits in a PR.
        o	Commits in a single PR should be related.
        o	Major new features or bug fixes should reference a CHIRP issue.
        o	New drivers should be accompanied by a test image in tests/images (except for thin aliases where the 
            driver is sufficiently tested already).

    o	Please also follow these guidelines:

        o	Keep cleanups in separate commits from functional changes.
        o	Please write a reasonable commit message, especially if making some change that isn't totally obvious 
            (such as adding a new model, adding a feature, etc).
        o	Do not add new py2-compatibility code (No new uses of six, future, etc).
        o	All new drivers should set NEEDS_COMPAT_SERIAL=False and use MemoryMapBytes.
        o	New drivers and radio models will affect the Python3 test matrix. You should regenerate this file with 
            tox -emakesupported and include it in your commit.
    ===================================
	
18)	After TOX tests are complete and the above checklists are fulfilled, either with or without issues, wait for 
    comments via chirp_devel, or for merging into the Master. Otherwise, make any necessary changes, and
    try again using the same PR.

===================================