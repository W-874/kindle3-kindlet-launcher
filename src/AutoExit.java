package com.mobileread.ixtab.kindlelauncher;

import java.awt.Component;
import java.awt.Container;
import java.awt.EventQueue;
import java.awt.event.ComponentAdapter;
import java.awt.event.ComponentEvent;
import java.awt.event.FocusEvent;
import java.awt.event.FocusListener;

import com.amazon.kindle.kindlet.KindletContext;
import com.mobileread.ixtab.kindlelauncher.ui.UIAdapter;

/** Requests normal KUAL exit only after the launcher owns keyboard focus. */
public final class AutoExit extends ComponentAdapter implements FocusListener, Runnable {
    private final Container root;
    private final Component target;
    private final KindletContext context;
    private boolean queued; // Only accessed on the event-dispatch thread.
    private volatile boolean cancelled; // stop() may run on the lifecycle thread.

    private AutoExit(Container root, Component target, KindletContext context) {
        this.root = root;
        this.target = target;
        this.context = context;
    }

    public static void arm(KindletContext context, Component target) {
        Container root = context.getRootContainer();
        AutoExit exit = new AutoExit(root, target, context);
        target.addFocusListener(exit);
        root.addComponentListener(exit);
        exit.requestFocus();
    }

    public static void cancel(Component target) {
        if (target == null) return;
        FocusListener[] listeners = target.getFocusListeners();
        for (int i = 0; i < listeners.length; i++) {
            if (listeners[i] instanceof AutoExit) {
                ((AutoExit) listeners[i]).detach();
            }
        }
    }

    private void detach() {
        cancelled = true;
        target.removeFocusListener(this);
        root.removeComponentListener(this);
    }

    private void requestFocus() {
        if (cancelled) return;
        root.validate();
        root.repaint();
        target.requestFocus();
        if (target.hasFocus()) schedule();
    }

    public void componentShown(ComponentEvent event) {
        requestFocus();
    }

    public void focusGained(FocusEvent event) {
        schedule();
    }

    public void focusLost(FocusEvent event) {
        // A later focusGained will schedule exit if this window becomes active again.
    }

    private void schedule() {
        if (cancelled || queued) return;
        queued = true;
        EventQueue.invokeLater(this);
    }

    public void run() {
        queued = false;
        if (cancelled || !target.isShowing() || !target.hasFocus()) return;
        detach();
        UIAdapter.INSTANCE.suicide(context);
    }
}
