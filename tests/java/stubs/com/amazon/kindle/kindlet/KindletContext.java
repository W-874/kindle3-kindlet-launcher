package com.amazon.kindle.kindlet;

import java.awt.Container;

/** Test-only boundary type: the minimum KindletContext surface AutoExit calls. */
public interface KindletContext {
    Container getRootContainer();
}
