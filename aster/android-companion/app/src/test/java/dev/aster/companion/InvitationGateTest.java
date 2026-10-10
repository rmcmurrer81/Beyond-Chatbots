package dev.aster.companion;

public final class InvitationGateTest {
    static int checks;
    static void check(boolean condition) { checks++; if (!condition) throw new AssertionError("Check " + checks); }
    static InvitationGate.Invite invite(String id, String owner, long start, long end) {
        return new InvitationGate.Invite(id, owner, start, end);
    }
    public static void main(String[] args) {
        var gate = new InvitationGate("demo-owner");
        check(!gate.networkEnabled()); check(!gate.microphoneAllowed());
        check(!gate.receive(invite("a", "other", 100, 160), 100));
        check(!gate.receive(invite("a", "demo-owner", 100, 160), 160));
        check(!gate.receive(invite("a", "demo-owner", 101, 160), 100));
        check(!gate.receive(invite("a", "demo-owner", 100, 161), 100));
        check(!gate.receive(invite("a", "demo-owner", Long.MIN_VALUE, Long.MAX_VALUE), 100));
        check(!gate.receive(null, 100));
        check(gate.receive(invite("a", "demo-owner", 100, 160), 100));
        check(!gate.receive(invite("b", "demo-owner", 100, 160), 100));
        check(!gate.answer("wrong", 100)); check(!gate.isAnswered());
        check(gate.answer("a", 101)); check(gate.isAnswered());
        check(!gate.answer("a", 102)); check(!gate.microphoneAllowed());
        gate.dismiss(); check(!gate.isAnswered());
        check(!gate.receive(invite("a", "demo-owner", 100, 160), 102));
        check(gate.receive(invite("b", "demo-owner", 100, 160), 102));
        check(!gate.answer("b", 160)); gate.dismiss();
        check(!gate.answer("b", 150));
        check(InvitationGate.validEndpoint("https://workstation.example:8443"));
        for (String invalid : new String[] {"http://192.168.1.2", "https://u:p@host", "https://host/?token=x", "https://host/#x", "https://host/path", "https://host:0", "https://host:65536", "garbage"}) check(!InvitationGate.validEndpoint(invalid));
        var bounded = new InvitationGate("owner");
        for (int i=0; i<1024; i++) { check(bounded.receive(invite("i-"+i,"owner",100,160),100)); bounded.dismiss(); }
        check(!bounded.receive(invite("overflow","owner",100,160),100));
        System.out.println("PASS: " + checks + " protocol assertions (offline; no TLS/network/device test)");
    }
}
