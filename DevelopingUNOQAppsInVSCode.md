# Developing UNO Q Apps in VS Code

Oct 7, 2026 · @Chris Rogers

## Overview

After this setup, you write code in VS Code on your laptop, press one key, and it runs on your UNO Q. GitHub holds the master copy of all your apps, so your work is backed up and you can get it on any computer.

How the pieces connect:

- **Laptop (VS Code):** where you edit. A script called `deploy.py` (in a `tools` folder) copies your app to the board and starts it.
- **UNO Q:** where your app runs. Its apps live in `/home/arduino/ArduinoApps`.
- **GitHub:** a private repo with a copy of that folder. You push from the laptop, and the board can pull from it.

Before you start, you need:

- An UNO Q that is already set up with Arduino App Lab and connected to Wi-Fi.
- Your board's name and the password you chose when setting it up.
- A laptop with **VS Code** and **Python 3** installed. On Windows you need Windows 10 or later.
- A **GitHub** account.
- The file `unoq-vscode-kit.zip` from your instructor.
- Your laptop and board on the **same network**. Some campus networks block devices from talking to each other. If you get stuck, try a home network or a phone hotspot.

## Step 1: Find your board's name and IP address

You need both: the IP address is tried first, and the name is a backup. In the examples below, the board is called `Fred2`. Replace that with your board's name everywhere.

Open a terminal on your laptop (**Terminal** on Mac, **PowerShell** on Windows) and connect to the board by name:

```
ssh arduino@Fred2.local
```

If it asks "Are you sure you want to continue connecting?", type `yes`. Then enter the board password you chose during setup. Your prompt will change to `arduino@Fred2:~$`, which means you are now typing commands on the board.

Get the IP address:

```
hostname -I
```

Write down the first number it prints, such as `10.5.14.200`. Type `exit` to return to your laptop.

If `Fred2.local` doesn't connect, find the IP another way: check your board's info in App Lab, or open a terminal on the board through App Lab and run `hostname -I` there. Then connect with `ssh arduino@<IP>` instead.

**Note:** the IP can change when the board reconnects to Wi-Fi. If deploying stops working later, this is the first thing to check.

## Step 2: Set up passwordless login from your laptop

The deploy script logs into the board automatically, so it can't stop to ask for a password. You fix this by giving the board your laptop's **SSH key**. Do this once per laptop.

**Make a key** (skip if you already have one). On your laptop:

```
ssh-keygen -t ed25519
```

Press Enter at every question, including the passphrase. It prints a fingerprint and a box of random symbols; you can ignore both.

**Copy the key to the board.** On a **Mac**:

```
ssh-copy-id arduino@10.5.14.200
```

On **Windows** (in PowerShell), use this instead, because `ssh-copy-id` doesn't exist there:

```
type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh arduino@10.5.14.200 "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"
```

Use your board's IP from Step 1. It will ask for the board password one last time.

**Test it:**

```
ssh arduino@10.5.14.200 hostname
```

It should print your board's name **without** asking for a password. If it just hangs, press Ctrl+C and see Troubleshooting.

## Step 3: Create an empty GitHub repo

On github.com, click **New repository**.

1. Name it `ArduinoApps`.
2. Choose **Private**.
3. Leave **Add a README**, **.gitignore**, and **license** all unchecked. The repo must be completely empty, or the first push in Step 4 will be rejected.
4. Click **Create repository**.

Keep the page open. You'll need its SSH address, which looks like `git@github.com:YOUR-USERNAME/ArduinoApps.git`.

## Step 4: Push your board's apps to GitHub

This step happens **on the board**, in several short parts.

### 4a. Log in to the board

From your laptop, run `ssh arduino@10.5.14.200`.

### 4b. Set up Git

```
git --version || sudo apt install -y git
git config --global user.name "Your Name"
git config --global user.email "you@example.edu"
```

### 4c. Make a key on the board

Press Enter at every question:

```
ssh-keygen -t ed25519 -C "Fred2"
cat ~/.ssh/id_ed25519.pub
```

The second command prints **one line** that starts with `ssh-ed25519` and ends with `Fred2`. Copy that whole line. Only ever share the file ending in `.pub`; the one without `.pub` is private and never leaves the board.

### 4d. Give the key to GitHub

On your GitHub repo page, go to **Settings → Deploy keys → Add deploy key**. Paste the line into **Key**, give it a title like "Fred2", check **Allow write access**, and save. A deploy key only works for this one repo.

### 4e. Test the connection

On the board, run:

```
ssh -T git@github.com
```

Type `yes` if asked. It should greet you, even though it adds that it doesn't provide shell access.

### 4f. Create the repo and stage your files

```
cd ~/ArduinoApps
printf '.cache/\n__pycache__/\n*.pyc\n.DS_Store\n' > .gitignore
git init -b main
git add .
git status
```

Check the `git status` list: no `.cache` folders should appear. Those hold the Python libraries App Lab installs on the board, and they don't belong on GitHub.

### 4g. Commit

```
git commit -m "Initial commit from my UNO Q"
```

### 4h. Connect to GitHub and push

Replace `YOUR-USERNAME` with your GitHub username:

```
git remote add origin git@github.com:YOUR-USERNAME/ArduinoApps.git
git push -u origin main
```

### 4i. Check GitHub and log out

Refresh the GitHub page. Your app folders should be there. Type `exit` to leave the board.

## Step 5: Copy the repo to your laptop and add the kit

**Clone the repo.** Your laptop needs Git: on a Mac, run `git --version` and accept the offer to install developer tools; on Windows, install Git from git-scm.com. Then in VS Code:

1. Open the Command Palette (**Cmd+Shift+P** on Mac, **Ctrl+Shift+P** on Windows).
2. Run **Git: Clone**, choose **Clone from GitHub**, and sign in when asked.
3. Pick your `ArduinoApps` repo and a folder to save it in.
4. Click **Open** when it finishes.

**Add the kit.** Unzip `unoq-vscode-kit.zip` and move its contents into the top level of your `ArduinoApps` folder:

- `.vscode/tasks.json` creates the Cmd+Shift+B choices (Step 6).
- `tools/deploy.py` copies your app to the board and starts it.
- `tools/Tufts_WiFi.py` advertises your board on the campus network (see Step 6).
- `tools/board_secrets.example.py` is the template for your board's address.
- `tools/config.py` and `tools/README.md` are support files and notes.
- `CLAUDE.md` tells Claude Code how to work with your board (Step 7).

On a Mac, Finder hides the `.vscode` folder because its name starts with a dot. Press **Cmd+Shift+.** in Finder to show it.

**Point the script at your board.** Your settings live in their own file, `tools/board_secrets.py`, so you can re-unzip a newer kit later without losing them. The kit doesn't include that file. Make it by running any command once, in a terminal in your `ArduinoApps` folder:

```
python3 tools/deploy.py --cmd "hostname"
```

(On Windows, type `python` instead of `python3`.) It prints "Created board_secrets.py with default values". Open `tools/board_secrets.py` and put in your board's IP and name from Step 1:

```
HOSTS = [
    "10.5.14.200",     # your board's IP address
    "Fred2.local",     # your board's name + .local
]
USER = "arduino"
BOARD_NAME = "Fred2"
BOARD_IP = "10.5.14.200"
```

`BOARD_NAME` and `BOARD_IP` are only used by `Tufts_WiFi.py`. These settings are for your own board and stay on your laptop.

**Keep your address private (optional).** Add the line `tools/board_secrets.py` to the `.gitignore` file in your `ArduinoApps` folder so your own settings aren't uploaded.

**Save the kit to GitHub.** In VS Code's **Source Control** panel, type a message like "Add deploy kit", click **Commit**, then **Sync Changes**.

## Step 6: Run an app from VS Code

1. Open any file inside the app you want to run, such as `my-app/python/main.py`. The script uses the open file to decide which app to run.
2. Press **Cmd+Shift+B** (Mac) or **Ctrl+Shift+B** (Windows).
3. Pick one of the choices that appears:
   - **Run on UNO Q**: copies the app to the board and starts it.
   - **Python in UNO Q container**: opens a Python prompt in the terminal. If an app is running, the prompt is inside that app, so `arduino.app_utils` works. If nothing is running, it is plain Python on the board's Linux side.
   - **Terminal on UNO Q**: opens a command-line session on the board, over USB or Wi-Fi. Type `exit` to leave.
   - **Advertise UNO Q on Tufts WiFi**: runs `Tufts_WiFi.py` so your board can be found on the campus network. It needs the `zeroconf` package once (`pip install zeroconf`). Press Ctrl+C in its terminal to stop.

The terminal panel shows each step:

```
Trying USB (adb) ... no device
Trying 10.5.14.200 ... connected
$ ssh ... arduino-app-cli app stop /home/arduino/ArduinoApps/my-app
$ scp ... 
$ ssh ... arduino-app-cli app start /home/arduino/ArduinoApps/my-app
```

It stops the app if it's running, copies your files to the board (replacing the old versions), and starts it. Only your own files are copied; the board keeps its installed Python libraries, so apps start quickly. After starting, it shows the app's first log messages and, if your app has a web page, the address to open it.

**USB works too.** If the board is plugged into your laptop with a USB cable and `adb` is installed, the script uses USB first and doesn't need Wi-Fi at all. Over USB, the web page opens at `http://localhost:7007`. The board runs one app at a time, so starting an app stops whichever one was running.

You can also run any command on the board without remembering its address:

```
python3 tools/deploy.py --cmd "arduino-app-cli --help"
```

On Windows, type `python` instead of `python3`.

## Step 7 (optional): Use Claude Code in VS Code

Claude Code runs on your laptop and can edit your app, deploy it to the board, read the errors, and fix them. It needs a paid Claude plan; the free plan doesn't include it.

1. In VS Code's Extensions panel, search for **Claude Code** and install it.
2. Open the Claude Code panel and sign in with your Claude account.
3. Ask for a change, for example: "In my-app, show the button state on the web page, then deploy and test it."

Claude reads `CLAUDE.md` automatically, so it already knows how to reach your board through `tools/deploy.py`. Review its changes in the Source Control panel before you commit them.

## Daily workflow

The one rule: **edit in one place at a time. Before switching, push from where you were, then pull where you're going.**

**Normal routine (editing in VS Code):**

1. Edit your app on the laptop.
2. Press Cmd/Ctrl+Shift+B to test it on the board. Repeat as often as you like.
3. When it works, commit and **Sync Changes** in Source Control.

**Making the board's Git copy match GitHub** (do this now and then, or before editing on the board):

```
python3 tools/deploy.py --cmd "cd ~/ArduinoApps && git fetch && git reset --hard origin/main"
```

This makes the board an exact copy of GitHub, and it throws away any uncommitted changes on the board. A plain `git pull` would complain, because deploying makes the board's files look modified to Git.

**If you create or edit an app in App Lab:** push it from the board first, then pull on the laptop.

```
python3 tools/deploy.py --cmd "cd ~/ArduinoApps && git add . && git commit -m 'Changes from App Lab' && git push"
```

Then click **Sync Changes** in VS Code.

**Things to know:**

- Deploying copies and replaces files but never **deletes** them on the board. If you delete or rename a file, remove the old copy with `python3 tools/deploy.py --cmd "rm /home/arduino/ArduinoApps/my-app/python/old_file.py"`.
- Edits made only on the board are overwritten the next time you deploy that app.

## Troubleshooting

| What you see | What to do |
| --- | --- |
| Deploy says "Couldn't reach the board at any address" | The board's IP probably changed. Find the new one (Step 1) and update `HOSTS` in `tools/board_secrets.py`. If the board is plugged in over USB, it should connect without this. Also check the board is on and on the same network. |
| `ssh` or `ssh-copy-id` hangs with no output | Your laptop can't reach the board. Press Ctrl+C. Try the IP instead of the `.local` name, or move both to a home network or phone hotspot. |
| "Could not resolve hostname" | The `.local` name doesn't work on this network. Use the IP address. |
| Asked for a password after Step 2 | The key copy didn't work. Repeat "Copy the key to the board" in Step 2. |
| "Host key verification failed" | A different device now has your board's old IP. Find your board's current IP and update `HOSTS` in `tools/board_secrets.py`. |
| Push rejected: "remote contains work that you do not have locally" | The GitHub repo wasn't empty. If it only has a README, run `git push -u --force origin main` on the board. |
| "Permission denied (publickey)" when pushing from the board | The deploy key is missing or lacks write access. Recheck Step 4 and make sure **Allow write access** is checked. |
| Thousands of files in `git status` or during a deploy | A `.cache` folder is being included. Make sure `.gitignore` contains `.cache/`, and use the `tools/deploy.py` from the kit. |
| Can't find `.vscode` after unzipping | Finder hides it. Press Cmd+Shift+. to show hidden files. |
| "doesn't look like an App (no app.yaml)" | Click into a file inside an app folder before pressing Cmd/Ctrl+Shift+B. (The Python and Advertise choices don't need this.) |
| Cmd+Shift+B runs something straight away instead of showing choices | A default build task is set in your own VS Code settings (**Terminal → Configure Default Build Task**). Remove the default so the choices appear. |
| `Tufts_WiFi.py` says no module named `zeroconf` | Run `pip install zeroconf` once. |
