package fss.core;

import static fss.core.RetrieveRequest.MAX_EVENTS_LIMIT;
import static fss.core.RetrieveRequest.MAX_WINDOW_NS;
import static fss.core.TestEvents.T0;
import static fss.core.TestEvents.ev;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.nio.file.Path;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;

/** Contract v0 section 5: bounded window, max_events, truncated flag, filters. */
class RetrieveContractTest {

    @TempDir
    Path dir;
    BlockStore store;

    @BeforeEach
    void fill() throws Exception {
        store = BlockStore.open(dir.resolve("s.dat"));
        for (int i = 0; i < 10; i++) { // 10 events: sources 298/474, types 0x10/0x20, ts T0..T0+9
            store.append(ev(i % 2 == 0 ? 298 : 474, T0 + i, i < 5 ? 0x10 : 0x20, 6));
        }
    }

    @Test
    void invertedOrEmptyRangesRejected() {
        assertThrows(IllegalArgumentException.class, () -> RetrieveRequest.forAllSources(T0, T0, 10));
        assertThrows(IllegalArgumentException.class, () -> RetrieveRequest.forAllSources(T0 + 1, T0, 10));
    }

    @Test
    void windowLimitEnforcedInclusive() {
        RetrieveRequest.forAllSources(T0, T0 + MAX_WINDOW_NS, 10);
        assertThrows(IllegalArgumentException.class,
                () -> RetrieveRequest.forAllSources(T0, T0 + MAX_WINDOW_NS + 1, 10));
        assertThrows(IllegalArgumentException.class, () -> RetrieveRequest.forAllSources(0, -1L, 10),
                "the whole u64 range is not a bounded request");
    }

    @Test
    void unsignedWindowsAcrossTheSignBit() {
        RetrieveRequest q = RetrieveRequest.forAllSources(Long.MAX_VALUE, Long.MIN_VALUE, 10); // [2^63-1, 2^63)
        assertEquals(Long.MIN_VALUE, q.tEndNs());
        RetrieveRequest.forAllSources(-1000L, -1L, 10); // [2^64-1000, 2^64-1)
    }

    @ParameterizedTest
    @CsvSource({"0", "-1", "10001"})
    void maxEventsRangeEnforced(int bad) {
        assertThrows(IllegalArgumentException.class, () -> RetrieveRequest.forAllSources(T0, T0 + 10, bad));
    }

    @Test
    void maxEventsBoundariesAccepted() throws Exception {
        assertEquals(1, store.retrieve(RetrieveRequest.forAllSources(T0, T0 + 10, 1)).events().size());
        assertEquals(10, store.retrieve(RetrieveRequest.forAllSources(T0, T0 + 10, MAX_EVENTS_LIMIT)).events().size());
    }

    @ParameterizedTest
    @CsvSource({"11,10,false", "10,10,false", "9,9,true", "1,1,true"})
    void truncatedFlagIsExact(int max, int returned, boolean truncated) throws Exception {
        RetrieveResult r = store.retrieve(RetrieveRequest.forAllSources(T0, T0 + 10, max));
        assertEquals(returned, r.events().size());
        assertEquals(truncated, r.truncated());
    }

    @Test
    void intervalIsHalfOpen() throws Exception {
        List<Long> ts = store.retrieve(RetrieveRequest.forAllSources(T0 + 3, T0 + 5, 10)).events()
                .stream().map(EventRecord::timestampNs).sorted().toList();
        assertEquals(List.of(T0 + 3, T0 + 4), ts);
    }

    @Test
    void sourceFilterAndAllSources() throws Exception {
        assertEquals(Set.of(474), sources(store.retrieve(RetrieveRequest.forSource(474, T0, T0 + 10, 100))));
        assertEquals(Set.of(298, 474), sources(store.retrieve(RetrieveRequest.forAllSources(T0, T0 + 10, 100))));
        assertTrue(store.retrieve(RetrieveRequest.forSource(901, T0, T0 + 10, 100)).events().isEmpty());
    }

    @Test
    void eventTypeFilter() throws Exception {
        RetrieveResult r = store.retrieve(RetrieveRequest.forAllSources(T0, T0 + 10, 100).withEventType(0x20));
        assertEquals(5, r.events().size());
        assertTrue(r.events().stream().allMatch(e -> e.eventType() == 0x20));
        assertFalse(r.truncated());
    }

    @Test
    void producerTimestampsAreReturnedVerbatim() throws Exception {
        long odd = Long.MIN_VALUE + 123_456_789L;
        store.append(ev(298, odd, 0x10, 1));
        EventRecord got = store.retrieve(RetrieveRequest.forSource(298, odd, odd + 1, 1)).events().get(0);
        assertEquals(odd, got.timestampNs());
    }

    private static Set<Integer> sources(RetrieveResult r) {
        return r.events().stream().map(EventRecord::sourceId).collect(Collectors.toSet());
    }

    @org.junit.jupiter.api.AfterEach
    void close() throws Exception {
        store.close();
    }
}
