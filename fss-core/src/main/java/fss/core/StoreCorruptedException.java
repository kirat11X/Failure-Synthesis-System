package fss.core;

import java.io.IOException;

/** A record that passed recovery no longer validates (media corruption after open). */
public final class StoreCorruptedException extends IOException {
    private static final long serialVersionUID = 1L;

    public StoreCorruptedException(String message) {
        super(message);
    }
}
