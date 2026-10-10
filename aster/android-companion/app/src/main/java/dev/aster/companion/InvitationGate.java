package dev.aster.companion;

import java.net.URI;
import java.util.HashSet;
import java.util.Set;

/** Offline protocol model. Validation does NOT authenticate a network sender. */
public final class InvitationGate {
    public static final long MAX_LIFETIME_SECONDS = 60;
    private final String ownerDevice;
    private final Set<String> consumed = new HashSet<>();
    private Invite pending;
    private boolean answered;

    public record Invite(String id, String destination, long issuedAt, long expiresAt) {}

    public InvitationGate(String ownerDevice) {
        if (ownerDevice == null || ownerDevice.isBlank()) throw new IllegalArgumentException("Owner required");
        this.ownerDevice = ownerDevice;
    }

    /** HTTPS syntax check only; live adapter must ALSO authenticate TLS and enrolled peer. */
    public static boolean validEndpoint(String candidate) {
        try {
            URI uri = URI.create(candidate);
            return "https".equals(uri.getScheme()) && uri.getHost() != null
                && !uri.getHost().isBlank() && uri.getRawUserInfo() == null
                && uri.getRawQuery() == null && uri.getRawFragment() == null
                && (uri.getPort() == -1 || uri.getPort() > 0 && uri.getPort() <= 65535)
                && (uri.getRawPath().isEmpty() || uri.getRawPath().equals("/"));
        } catch (RuntimeException e) { return false; }
    }

    private boolean current(Invite invite, long now) {
        return invite != null && invite.id() != null && invite.id().matches("[A-Za-z0-9-]{1,80}")
            && ownerDevice.equals(invite.destination()) && invite.issuedAt() >= 0
            && invite.issuedAt() <= now && invite.expiresAt() > now
            && invite.expiresAt() > invite.issuedAt()
            && invite.expiresAt() - invite.issuedAt() <= MAX_LIFETIME_SECONDS;
    }

    public synchronized boolean receive(Invite invite, long now) {
        if (pending != null || !current(invite, now) || consumed.contains(invite.id()) || consumed.size() >= 1024) return false;
        consumed.add(invite.id()); // bounded, fail closed when full; live implementation needs durable storage
        pending = invite;
        answered = false;
        return true;
    }

    public synchronized boolean answer(String id, long now) {
        if (answered || !current(pending, now) || !pending.id().equals(id)) return false;
        answered = true;
        return true;
    }

    public synchronized void dismiss() { pending = null; answered = false; }
    public synchronized boolean isAnswered() { return answered; }
    public boolean microphoneAllowed() { return false; } // no media implementation in this release
    public boolean networkEnabled() { return false; }
}
