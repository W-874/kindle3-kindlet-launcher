package com.mobileread.ixtab.kindlelauncher;

import com.amazon.kindle.kindlet.Kindlet;
import com.amazon.kindle.kindlet.KindletContext;
import com.amazon.kindle.kindlet.ui.KLabel;

import java.awt.Component;
import java.awt.Container;
import java.awt.GridBagConstraints;
import java.awt.GridBagLayout;
import java.io.File;
import java.io.IOException;

/**
 * Universal Standalone App Launcher for Kindle 4 (K4NT / KDK 1.0)
 * 
 * This class implements the Amazon KDK 1.0 Kindlet lifecycle to function as
 * a native Kindle "book" / document shortcut on the Home screen.
 * 
 * Lifecycle:
 * 1. onCreate(KindletContext): Framework passes the device context and container.
 * 2. onStart(): Displays user prompt instructions and spawns the background worker.
 * 3. longStart(): Launches the target Linux shell script / native binary.
 * 4. onStop() / onDestroy(): Cleanly handles termination when user presses [BACK].
 */
public class KindleLauncher implements Kindlet {

    // Configuration constants (customized per application)
    private static final String APP_TITLE = "KOReader Launcher";
    private static final String TIMEOUT_NOTE = "If you see this screen > 10s: press [BACK] to exit.";
    private static final String EXIT_NOTE = "On KOReader exit: press [BACK] twice if frozen.";
    private static final String SHELL_COMMAND = "/mnt/us/koreader/koreader.sh";
    private static final String WORKING_DIRECTORY = "/mnt/us";

    private KindletContext context;

    /**
     * Called by Kindle OS when the Kindlet is initialized.
     */
    public void onCreate(KindletContext context) {
        this.context = context;
    }

    /**
     * Called when the Kindlet becomes active / visible on screen.
     */
    public void onStart() {
        // Initialize UI with informative status instructions
        displayStatusScreen(APP_TITLE, TIMEOUT_NOTE, EXIT_NOTE);

        // Run target application in a separate worker thread so CVM does not block
        new Thread(new Runnable() {
            public void run() {
                longStart();
            }
        }).start();
    }

    /**
     * Executes the target Linux command and manages execution lifecycle.
     */
    public void longStart() {
        try {
            execute(SHELL_COMMAND, WORKING_DIRECTORY, true);
        } catch (Throwable t) {
            // Safe fallback if execution fails
            t.printStackTrace();
        }
    }

    /**
     * Displays a clean, centered 3-line E-Ink status screen.
     */
    public void displayStatusScreen(String title, String timeoutMsg, String exitMsg) {
        if (context == null) return;
        Container container = context.getRootContainer();
        if (container == null) return;

        container.removeAll();
        container.setLayout(new GridBagLayout());

        GridBagConstraints gbc = new GridBagConstraints();
        gbc.gridx = 0;
        gbc.fill = GridBagConstraints.HORIZONTAL;
        gbc.weightx = 1.0;

        // Line 1: Header title
        container.add(new KLabel(title), gbc);

        // Line 2: Startup / timeout instruction
        container.add(new KLabel(timeoutMsg), gbc);

        // Line 3: Exit return instruction
        container.add(new KLabel(exitMsg), gbc);

        container.validate();
        container.repaint();
    }

    /**
     * Spawns the native command on the Kindle Linux system.
     */
    public Process execute(String command, String workDir, boolean background) throws IOException {
        String[] cmdArray = new String[] { "/bin/sh", "-c", command };
        File dir = (workDir != null) ? new File(workDir) : null;
        return Runtime.getRuntime().exec(cmdArray, null, dir);
    }

    public void onStop() {
        // Handle when Kindle OS pauses the Kindlet
    }

    public void onDestroy() {
        // Clean up resources upon exit
        this.context = null;
    }
}
