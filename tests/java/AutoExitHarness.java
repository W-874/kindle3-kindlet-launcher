import java.awt.Component;
import java.awt.Container;
import java.awt.EventQueue;
import java.awt.event.ComponentEvent;
import java.awt.event.FocusEvent;

import com.amazon.kindle.kindlet.KindletContext;
import com.mobileread.ixtab.kindlelauncher.AutoExit;
import com.mobileread.ixtab.kindlelauncher.ui.UIAdapter;

/**
 * Drives the real, precompiled template/AutoExit.class through AWT listener
 * callbacks. Only the peer-dependent Component state (showing / focus owner)
 * and the KindletContext / UIAdapter boundary types are simulated. Each
 * scenario prints key=value lines; the Python test asserts on them.
 */
public final class AutoExitHarness {
    /** Focusable target whose showing/focus state is controlled by the test. */
    static final class FakeTarget extends Component {
        boolean showing = true;
        boolean focused;
        boolean grantFocusOnRequest;

        public boolean isShowing() { return showing; }
        public boolean hasFocus() { return focused; }

        public void requestFocus() {
            if (grantFocusOnRequest) gain();
        }

        void gain() {
            focused = true;
            processFocusEvent(new FocusEvent(this, FocusEvent.FOCUS_GAINED));
        }

        void lose() {
            focused = false;
            processFocusEvent(new FocusEvent(this, FocusEvent.FOCUS_LOST));
        }
    }

    static final class FakeRoot extends Container {
        void showRoot() {
            processComponentEvent(new ComponentEvent(this, ComponentEvent.COMPONENT_SHOWN));
        }
    }

    static FakeTarget target;
    static FakeRoot root;
    static KindletContext context;

    static void setUp() {
        UIAdapter.calls = 0;
        target = new FakeTarget();
        root = new FakeRoot();
        context = new KindletContext() {
            public Container getRootContainer() { return root; }
        };
    }

    /** Runs on the event-dispatch thread; anything it queues runs after it returns. */
    static void onEdt(Runnable task) throws Exception {
        EventQueue.invokeAndWait(task);
    }

    /** Waits for every previously queued EDT event without sleeping. */
    static void drain() throws Exception {
        EventQueue.invokeAndWait(new Runnable() { public void run() { } });
    }

    static void report(String key, Object value) {
        System.out.println(key + "=" + value);
    }

    static void reportListeners(String prefix) {
        report(prefix + ".focusListeners", target.getFocusListeners().length);
        report(prefix + ".componentListeners", root.getComponentListeners().length);
    }

    public static void main(String[] args) throws Exception {
        String scenario = args[0];
        setUp();
        if (scenario.equals("no_focus_no_exit")) {
            target.grantFocusOnRequest = false;
            onEdt(new Runnable() { public void run() { AutoExit.arm(context, target); } });
            drain();
            onEdt(new Runnable() { public void run() { root.showRoot(); } });
            drain();
            report("calls", UIAdapter.calls);
            reportListeners("armed");
        } else if (scenario.equals("focus_exits_once_async")) {
            onEdt(new Runnable() { public void run() { AutoExit.arm(context, target); } });
            drain();
            report("calls.beforeFocus", UIAdapter.calls);
            onEdt(new Runnable() {
                public void run() {
                    target.gain();
                    report("calls.insideFocusEvent", UIAdapter.calls);
                }
            });
            drain();
            report("calls", UIAdapter.calls);
            report("onEventThread", UIAdapter.lastOnEventThread);
            reportListeners("after");
        } else if (scenario.equals("repeated_focus_exits_once")) {
            onEdt(new Runnable() { public void run() { AutoExit.arm(context, target); } });
            drain();
            onEdt(new Runnable() {
                public void run() {
                    target.gain();
                    target.gain();
                    target.gain();
                }
            });
            drain();
            report("calls", UIAdapter.calls);
            onEdt(new Runnable() { public void run() { target.gain(); root.showRoot(); } });
            drain();
            report("callsAfterExit", UIAdapter.calls);
        } else if (scenario.equals("cancel_queued_blocks_exit")) {
            onEdt(new Runnable() { public void run() { AutoExit.arm(context, target); } });
            drain();
            onEdt(new Runnable() {
                public void run() {
                    target.gain(); // exit is now queued behind this task
                    AutoExit.cancel(target);
                }
            });
            drain();
            report("calls", UIAdapter.calls);
            reportListeners("after");
            onEdt(new Runnable() { public void run() { target.gain(); root.showRoot(); } });
            drain();
            report("callsAfterLateEvents", UIAdapter.calls);
        } else if (scenario.equals("already_focused_schedules_immediately")) {
            target.focused = true; // already owns focus: no focusGained event will arrive
            onEdt(new Runnable() {
                public void run() {
                    AutoExit.arm(context, target);
                    report("calls.insideArm", UIAdapter.calls);
                }
            });
            drain();
            report("calls", UIAdapter.calls);
            reportListeners("after");
        } else if (scenario.equals("focus_lost_no_exit_then_regain")) {
            onEdt(new Runnable() { public void run() { AutoExit.arm(context, target); } });
            drain();
            onEdt(new Runnable() {
                public void run() {
                    target.gain();
                    target.lose(); // focus is gone before the queued exit runs
                }
            });
            drain();
            report("callsAfterLoss", UIAdapter.calls);
            reportListeners("afterLoss");
            onEdt(new Runnable() { public void run() { target.gain(); } });
            drain();
            report("callsAfterRegain", UIAdapter.calls);
            reportListeners("afterRegain");
        } else if (scenario.equals("hidden_no_exit_then_shown")) {
            target.showing = false;
            target.grantFocusOnRequest = true; // focus event while not showing
            onEdt(new Runnable() { public void run() { AutoExit.arm(context, target); } });
            drain();
            report("callsWhileHidden", UIAdapter.calls);
            reportListeners("hidden");
            target.showing = true;
            onEdt(new Runnable() { public void run() { root.showRoot(); } });
            drain();
            report("callsAfterShown", UIAdapter.calls);
            reportListeners("shown");
        } else {
            throw new IllegalArgumentException("unknown scenario " + scenario);
        }
        System.exit(0);
    }
}
