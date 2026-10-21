package com.mobileread.ixtab.kindlelauncher.ui;

import java.awt.EventQueue;

import com.amazon.kindle.kindlet.KindletContext;

/** Test-only boundary type: records the suicide(context) calls AutoExit makes. */
public class UIAdapter {
    public static final UIAdapter INSTANCE = new UIAdapter();

    public static volatile int calls;
    public static volatile boolean lastOnEventThread;

    public void suicide(KindletContext context) {
        lastOnEventThread = EventQueue.isDispatchThread();
        calls++;
    }
}
