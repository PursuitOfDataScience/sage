/* Sage — DOM touch-ups Streamlit cannot express declaratively.
 *
 * Two whole functions were deleted rather than fixed: example-card animation and
 * attachment-chip styling are now pure CSS keyed off `st.container(key=...)`
 * hooks. They used to find elements by matching visible English text and then
 * wrote hardcoded dark-mode colours as inline styles, which beat the light-mode
 * stylesheet — so on a light theme every hovered card stayed broken until rerun.
 * A third, the AI disclaimer, is now rendered by app.py: static text belongs in
 * the document rather than being appended into a container React owns.
 *
 * What is left injects the two controls Streamlit has no element for, scrolls the
 * page the way a chat is read, and measures the pinned bottom bar so app.css can
 * reserve exactly as much room for it as it actually takes.
 */
(function () {
    'use strict';

    // This script is served inside a components.html iframe, so `window` is the
    // iframe (0×0) and every measurement has to come from the page around it.
    var view = window.parent;
    var doc = view.document;

    var COPY_SVG = '<svg aria-hidden="true" focusable="false" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>';
    var CHECK_SVG = '<svg aria-hidden="true" focusable="false" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>';
    var CLIP_SVG = '<svg aria-hidden="true" focusable="false" xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>';
    // Filled, and rounded rather than a hard square: it is the same glyph every other
    // chat app stops a generation with, and a reader should not have to learn it here.
    var STOP_SVG = '<svg aria-hidden="true" focusable="false" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><rect x="4" y="4" width="16" height="16" rx="3"></rect></svg>';
    var CLOSE_SVG = '<svg aria-hidden="true" focusable="false" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12"></path></svg>';
    var PENCIL_SVG = '<svg aria-hidden="true" focusable="false" xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"></path><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"></path></svg>';

    function isProcessing() {
        return !!doc.getElementById('processing-signal');
    }

    // Every button this script creates carries this, and every lookup for a Streamlit
    // widget excludes it.
    //
    // Not defensive tidiness — this is the fix for a bug that shipped nothing but
    // silence. Streamlit reuses a container's DOM node across reruns and swaps its
    // class rather than rebuilding it, and the buttons injected here are not React's
    // to remove, so a node that had been an answer could arrive wearing a widget's key
    // with a copy button still inside it. `container.querySelector('button')` then
    // returned that copy button, and clicking a pencil copied an answer to the
    // clipboard instead of opening the editor — no error, nothing in a log, and no way
    // for a reader to tell the control from a broken one.
    var INJECTED = 'data-sage-injected';
    var NOT_INJECTED = 'button:not([' + INJECTED + '])';

    // Streamlit's own button inside a keyed element container, or null.
    function widgetButton(selector) {
        var host = doc.querySelector(selector);
        return host ? host.querySelector(NOT_INJECTED) : null;
    }

    function injected(tag) {
        var el = doc.createElement(tag);
        el.setAttribute(INJECTED, 'true');
        return el;
    }

    /* --- scrolling ------------------------------------------------------- */

    // Every box between the conversation and the document that could be the one
    // scrolling, innermost first.
    //
    // This used to force `overflow: auto` onto stAppViewContainer, stMain and body,
    // manufacturing three nested scrollports where Streamlit has one — and then
    // scroll all of them (plus documentElement) to the bottom. The scroll amounts
    // compounded, pushing the newest message clean above the top of the viewport
    // and slicing it in half. Forcing overflow also risked trapping content that
    // overflowed the welcome screen on a short window, so it is gone entirely:
    // Streamlit's own scrolling is left alone.
    //
    // What replaced it was a three-item list — `[data-testid="stMain"]`, the
    // scrolling element, documentElement — and both halves of that were wrong.
    //
    // The first entry is an unversioned Streamlit test id, which is the one kind of
    // rule this repo has written down not to write: Streamlit has put the app's
    // scrollbar on `.appview-container`, on `section.main` and on
    // `[data-testid="stMain"]` across the versions requirements.txt allows. This
    // app's own stylesheet sharpens it — app.css sets `overflow-x: hidden` on html,
    // body, stAppViewContainer and stMain, and CSS computes a `visible` axis to
    // `auto` beside a non-visible one, so all four are scroll containers here and
    // two of them were not on the list. On a page whose vertical overflow settles on
    // one of those two the list matched nothing, `scroller()` returned null, and
    // `autoScroll` returned on its first line: no per-turn pin, no settle, no
    // landing reset, on every turn at every window size. That is "the page stays
    // where it is after I send a prompt" — and it was invisible from the harness,
    // which defines the scrollport to be stMain or the document.
    //
    // The second half was `scrollHeight > clientHeight`, which is equally true of a
    // box that merely OVERFLOWS. `overflow: visible` reports the overflow and then
    // ignores every assignment to scrollTop, so a list that only asks about overflow
    // can pick a box that is never going to move and write into it all turn.
    //
    // So the chain is walked and the browser is asked which of them is a scroll
    // container, the same way `overlays()` asks it about fixed versus sticky.
    function ports() {
        var out = [];
        function add(el) { if (el && out.indexOf(el) === -1) out.push(el); }
        // Whatever Streamlit calls the box, the scrollport is an ancestor of the
        // conversation — so start at the conversation and walk out. The fallbacks are
        // the landing screen (no conversation yet) and a page mid-rebuild.
        var anchor = doc.querySelector('.chat-container')
            || doc.querySelector('.stChatMessage')
            || doc.querySelector('.welcome')
            || doc.querySelector('[data-testid="stMainBlockContainer"]')
            || doc.querySelector('.block-container')
            || doc.querySelector('[data-testid="stMain"]')
            || doc.body;
        for (var node = anchor; node; node = node.parentElement) add(node);
        add(doc.scrollingElement);
        add(doc.documentElement);
        return out;
    }

    // Does writing to this element's scrollTop move anything a reader can see? The
    // document always scrolls; anything else has to say so in its computed overflow.
    // `hidden` is deliberately not on the list: it takes a scrollTop, but it shows no
    // scrollbar, so it is a clipping wrapper rather than the page — and scrolling one
    // of those hides content with no way to bring it back.
    function scrollable(el) {
        if (el === doc.scrollingElement || el === doc.documentElement) return true;
        var overflow = view.getComputedStyle(el).overflowY;
        return overflow === 'auto' || overflow === 'scroll' || overflow === 'overlay';
    }

    // Move the view, now, whatever the stylesheet thinks about animation.
    //
    // `el.scrollTop = x` obeys `scroll-behavior`, and a `smooth` anywhere in the chain
    // — Streamlit's own stylesheet is not visible from this repo, and one line of it
    // would do — turns every scroll in this file into an animation that has not
    // started when the next line reads the position back. The reader sees the page
    // crawl, and this script reads its own unfinished scroll as a reader who has taken
    // the page over. `behavior: 'instant'` overrides the declaration; the assignment
    // stays as the fallback for anything without `scrollTo`.
    function scrollView(el, top) {
        if (el.scrollTo) {
            try {
                el.scrollTo({top: top, behavior: 'instant'});
                return;
            } catch (err) { /* older signature: fall through */ }
        }
        el.scrollTop = top;
    }

    // The single element that actually scrolls.
    function scroller() {
        var candidates = ports();
        var overflowing = null;
        for (var i = 0; i < candidates.length; i++) {
            var el = candidates[i];
            if (el.scrollHeight <= el.clientHeight + 1) continue;
            if (scrollable(el)) return el;
            // Remembered rather than returned. If nothing in the chain admits to
            // being a scroll container, writing into the box that at least overflows
            // is a guess — but the alternative is what shipped, which was to return
            // null and do nothing at all, and doing nothing is the bug.
            if (!overflowing) overflowing = el;
        }
        return overflowing;
    }

    // Streamlit's header strip is 3.75rem — 60px, full width, and on top of the
    // page — plus 16px so the question does not sit flush against it. Pinning
    // tighter puts the question underneath the header. (It was 112px while a
    // sticky bar of controls parked below that header; those have moved under the
    // input, and took their 36px of clearance with them.)
    var TOP_GAP = 76;
    // What should be left between the end of an answer and the input bar. Same
    // value as `--tail-gap` in app.css, which is how much room the page reserves
    // past its last message; this is the scroll that lands on it.
    var TAIL_GAP = 28;
    // Between the attachment chips and the top of the input bar. Matches the 0.35rem
    // the stylesheet offsets them by, so the room reserved is the room they occupy.
    var CHIP_GAP = 6;

    // The top edge of everything pinned at the bottom of the window.
    //
    // Not the bar's own top: the attachment chips are pinned above it and are `fixed`
    // too, so a gap measured to the bar is a gap measured underneath them. Every
    // spacing decision in this file is about how much room is left before the reader
    // runs into the composer, and the composer starts where the chips do.
    //
    // This was worth 5px of overlap with one row of chips and 38px with two, which is
    // the last message disappearing behind a chip — found by the `attached` screens in
    // tools/render_check.py the moment they were added.
    function composerTop(bar) {
        var top = bar.getBoundingClientRect().top;
        var chips = doc.querySelector('.st-key-attachments');
        if (chips) {
            var rect = chips.getBoundingClientRect();
            if (rect.height > 0 && rect.top < top) top = rect.top;
        }
        return top;
    }

    // Which question the chase is currently on ('' = none yet).
    var chasing = '';
    // Where the last scroll this script made left the view, so the next pass can tell
    // its own work from a reader who has scrolled somewhere else (-1 = nothing yet).
    var pinnedAt = -1;

    /* --- chrome measurement ---------------------------------------------- */

    // The page has to leave room for the fixed input bar, and the bar has to
    // leave room for the strip of controls under it. Neither height is a
    // constant — the disclaimer wraps to two or three lines on a narrow window —
    // so app.css takes both from here. A guess in the stylesheet is what left
    // either 50px of dead space under the newest answer or the answer 131px
    // underneath the input, depending on the viewport.
    function publish(name, px) {
        var root = doc.documentElement;
        var current = parseFloat(root.style.getPropertyValue(name));
        if (Math.abs(current - px) < 1) return;   // NaN on the first pass, so it sets
        root.style.setProperty(name, px + 'px');
    }

    // Both measured from the bottom of the window rather than as heights: what
    // has to be cleared is the band each one covers, and both are pinned to that
    // edge. Measuring the strip as a plain height would miss the gap it is lifted
    // off the edge by, and the bar would reserve too little by exactly that much.
    // Capped at a share of the window: a measurement that comes back as most of
    // the page means something upstream is wrong — an element that is not pinned
    // where the stylesheet thinks it is, or a rect read mid-rebuild — and
    // reserving that much space would push the conversation off screen. The cap
    // turns that into slightly-wrong spacing rather than an empty page.
    //
    // 0.55, not the 0.4 it was, because 0.4 was clipping a bar that was not wrong at
    // all. At 966x626 — a size CI renders — a composer with a paragraph in it measures
    // 290-298px, which is 48% of that window: real, correctly measured, and duly cut to
    // 250. The 40px it lost is 40px the page did not reserve, and on a page with
    // nothing to scroll that is the end of the newest answer sitting under the composer
    // with no way to bring it back out. Under-reserving hides content; over-reserving
    // only makes the page scroll, which is recoverable — so where the two disagree the
    // cap should lean high. Still a cap: a bar measured as more than half the window
    // is still capped, which is what keeps a bad rect from emptying the page.
    function band(element) {
        return Math.max(0, Math.min(rawBand(element),
                                    Math.round(view.innerHeight * 0.55)));
    }

    // The same measurement without the cap, for the things that are POSITIONS rather
    // than reservations. Capping a position does not make it safer, it moves it: the
    // attachment chips are pinned from `--bar-band`, so every pixel the cap clipped
    // slid them down into the input box. At 966x626 — a width CI renders — the cap
    // was already clipping 16-24px off a bar that tall, and with a paragraph typed
    // the chips ended up on top of the textarea.
    function rawBand(element) {
        return Math.max(0, Math.ceil(
            view.innerHeight - element.getBoundingClientRect().top));
    }

    // Does the input bar sit ON the page, or IN it?
    //
    // This is the question the whole bottom of the layout turns on, and it was
    // answered wrong for as long as this file has existed. If the bar is `fixed`
    // it is painted over the conversation, and the page has to leave a bar's worth
    // of room at the end or the newest answer hides underneath it. If it is
    // `sticky` it is *in the flow* at the end of the scrolling area — it already
    // occupies its own space, and reserving that much again is dead space at the
    // end of every conversation. Streamlit has done both across versions.
    //
    // tools/render_check.py modelled it as fixed, which is where the famous "the
    // newest answer is 131px underneath the input" measurement came from: a replica
    // asserting a layout the app may not have. Three rounds of trying to close a
    // gap by tuning padding, alignment and scrolling never touched the padding that
    // was the gap. So this asks the browser instead of guessing.
    //
    // A `sticky` anywhere in the chain wins, and this is the one part of the file
    // decided by the running app rather than by reasoning about CSS.
    //
    // In the abstract the opposite is true: `fixed` takes a subtree out of the flow
    // whatever is inside it, so a bar that is sticky inside something fixed is
    // painted over the page and needs room reserved. That version shipped, and the
    // gap at the end of the conversation came straight back — because Streamlit's own
    // stylesheet already leaves room for its own bar. Reserving it again is additive,
    // and additive is what a reader sees as 200px of nothing above the box they type
    // in. The reservation here is for the case where nothing in the chain is sticky
    // at all: then Streamlit is not pinning the bar and this has to.
    //
    // So the walk still goes to the top — it is how a fixed-only chain is told apart
    // from a sticky one — but sticky is the answer when both are present.
    function overlays(bar) {
        var streamlitPins = false;
        var overlaid = false;
        for (var node = bar; node && node !== doc.body; node = node.parentElement) {
            var position = view.getComputedStyle(node).position;
            if (position === 'sticky') streamlitPins = true;
            if (position === 'fixed' || position === 'absolute') overlaid = true;
        }
        return overlaid && !streamlitPins;
    }

    // Where the model picker sits: inside the input box, immediately left of Streamlit's
    // own send button. Measured from that button rather than written down, because it is
    // the thing the picker has to stay beside and app.css places it in a corner of a box
    // whose width tracks the viewport.
    //
    // The send button survives a turn — `markGenerating` leaves it in the DOM and paints
    // the stop square over it — so this does not lurch mid-answer. Nothing is published
    // when it cannot be found, which holds the last good position through the frames
    // where Streamlit is rebuilding the composer instead of snapping the picker into the
    // corner and back.
    function publishPickerSpot() {
        var send = sendButton();
        if (!send) return;
        var rect = send.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) return;
        publish('--pick-right', Math.round(view.innerWidth - rect.left) + 8);
        publish('--pick-bottom', Math.round(view.innerHeight - rect.bottom));
    }

    function measureChrome() {
        var strip = doc.querySelector('.st-key-composer-strip');
        var bar = doc.querySelector('[data-testid="stBottomBlockContainer"]');
        var chips = doc.querySelector('.st-key-attachments');
        // `--strip-h` is gone with the row it measured. The controls under the input
        // were a band the bar had to pad itself by; what is left is the model picker,
        // and it sits inside the box beside the send button, so there is nothing below
        // the input to reserve — which is the ~4rem of vertical space this bought back.
        publishPickerSpot();
        if (bar) {
            // Two numbers, and the difference between them matters.
            //
            // `--bar-band` is the bar alone, measured from the bottom of the window.
            // The attachment chips are pinned to it, so it must not include them.
            // `--bar-h` is what the page reserves at its end, which must include
            // them, because they are `fixed` and would otherwise sit on top of the
            // newest answer.
            //
            // Kept apart on purpose. One variable used for both would mean the chips'
            // position depended on a number their own height changed — a feedback
            // loop, and the last one of those in this file grew by 42px a frame until
            // it was the height of the window.
            // The band is published UNCONDITIONALLY, because it is a position: it is
            // where the bar's top edge is, and that is true whether Streamlit pinned
            // the bar with `fixed` or `sticky`. Gating it on `overlays()` — as the
            // reservation below is correctly gated — published 0 in the sticky shape,
            // which pinned the attachment chips 5.6px off the bottom of the window:
            // below the box they belong above, on top of the controls strip, and
            // taking no clicks at all. The reservation is the only thing `overlays()`
            // has an opinion about.
            publish('--bar-band', rawBand(bar));
            // How far the bar's centre is from the window's. Zero until the sidebar
            // is opened, and then half its width: Streamlit lays its bottom bar out
            // to the right of the panel, while the two rows this file pins — the
            // controls under the input and the attachment chips — are pinned to the
            // viewport at `left: 50%`. Without this they sit half a sidebar to the
            // left of the input they belong to.
            //
            // Measured rather than derived from the panel's width, because what has
            // to be matched is where Streamlit actually put the bar, and that has
            // been `fixed`, `sticky` and full-width across versions of it.
            var rect = bar.getBoundingClientRect();
            publish('--bar-shift',
                    Math.round(rect.left + rect.width / 2 - view.innerWidth / 2));
            // Height first, then decide: a container that is present at zero height
            // (or display:none) needs no gap reserved, and `composerTop` already
            // takes that view of the same node.
            var chipHeight = chips ? chips.getBoundingClientRect().height : 0;
            var chipRoom = chipHeight > 0 ? chipHeight + CHIP_GAP : 0;
            publish('--bar-h', (overlays(bar) ? band(bar) : 0) + chipRoom);
        }
        watch(strip, bar, chips);
    }

    // Re-measure whenever either one changes size, rather than only when the
    // MutationObserver below happens to fire. Both are sized by their text, so
    // they resize with no DOM change at all — a rewrapped disclaimer, a font
    // arriving late — and a published height that has gone stale is a stale
    // reservation: too small, and the newest answer sits under the input.
    var watcher = null;
    function watch(strip, bar, chips) {
        if (typeof ResizeObserver === 'undefined') return;
        try {
            if (!watcher) watcher = new ResizeObserver(measureChrome);
            // observe() on an element already observed is a no-op, so this can
            // run every sync and pick up the elements Streamlit just rebuilt.
            if (strip) watcher.observe(strip);
            if (bar) watcher.observe(bar);
            // The chips too: one more attached file adds a row, and the room the
            // page reserves has to follow it without waiting for the next rerun.
            if (chips) watcher.observe(chips);
        } catch (err) { /* the sync pass still measures */ }
    }

    // The bottom edge of the conversation, whatever ended it. Measuring only the
    // last answer left the space under a trailing failover notice or error card
    // exactly as dead as before — and a failover notice is precisely when the
    // reader is looking at the bottom of the page.
    function tail() {
        var edge = null;
        // `.stChatMessage` covers what is in flight as well as what has landed —
        // the status row and the streaming answer both render inside one. Without
        // it the slack above a short conversation is measured to the bottom of the
        // *question*, which pushes the answer being streamed under the input bar.
        // The two keyed note containers are on the list for the same reason the
        // notice is: they render at the END of the page, after the last message, and
        // a tail measured without them reserves room to the wrong edge. A refused
        // upload put 65 of its 80 pixels behind the input bar — the file did not
        // attach and the reason why was underneath the composer — because nothing
        // here had ever heard of it.
        var nodes = doc.querySelectorAll('[class*="st-key-answer-"], .user-message,' +
            '.stChatMessage, .notice, .error-card, [class*="st-key-error-actions"],' +
            '[class*="st-key-upload-notes"], [class*="st-key-prompt-notes"],' +
            // A question waiting its turn stands where the next question will, at the
            // very end of the page. Measured for the same reason the notes containers
            // are: a tail that stops short of it reserves room to the wrong edge, and
            // the thing left under the composer is the reader's own unsent question.
            '.queued-note,' +
            // The editor stands where a question stood and is several times its
            // height, so a tail measured without it stops at whatever preceded it.
            '[class*="st-key-edit-box-"]');
        nodes.forEach(function (node) {
            var bottom = node.getBoundingClientRect().bottom;
            if (edge === null || bottom > edge) edge = bottom;
        });
        return edge;
    }

    // Sit a conversation shorter than the window just above the composer, by
    // padding the space above it, so the reader is not left looking at a screenful
    // of nothing between the answer and the box they type in.
    //
    // NOT for a conversation the reader watched arrive, which in this app is all of
    // them. See `watched` below: the padding is correct for a short conversation
    // someone opens, and wrong for one that grew in front of them, because applying
    // it is a 463px jump at the exact moment they are reading.
    //
    // The stylesheet used to do this with `min-height: 100dvh` and
    // `justify-content: flex-end`. That shipped, and on the landing screen the
    // hero ended up above the top of the window: where flex puts the free space
    // depends on how Streamlit lays out the page around the block, and when the
    // guess is wrong the overflow goes out of the end of a scrollport that cannot
    // be scrolled back. Padding at the top can only push content down.
    //
    // It measures from the layout with no fill at all — set to zero, read, decide —
    // rather than subtracting its own last value from what it sees. Those are the
    // same number only while the padding is actually moving the conversation, and
    // the first version assumed that: a `padding-top` override in a media query
    // quietly won on every window under 720px, so the content never moved, "what is
    // left after the padding I applied" grew by the same 42px every frame, and the
    // fill ran away to the height of the window. Measuring the real thing costs one
    // extra reflow and cannot diverge, because nothing it reads depends on its own
    // previous output. If something is ignoring the padding, this now does nothing
    // instead of doing damage.
    // Has a turn run in front of the reader on this page?
    //
    // Parked on the parent window because Streamlit rebuilds this script's iframe on
    // every rerun, and the answer has to survive that: the whole point is to remember
    // something about a moment that has already passed. Cleared on the landing screen,
    // which is the one place the conversation genuinely starts again.
    //
    // Why it exists. `fill()` below pads above a short conversation so it sits by the
    // composer, and it is suppressed while an answer streams — so every short turn
    // ended with the padding arriving all at once. Measured: a question and a one-line
    // answer, or a question and a turn stopped before its first token, dropped 463px
    // down the window the instant the turn finished, and the editor moved the same way
    // when the pencil opened it. Reported as the stopped message ending up "near the
    // bottom of the page", and as the editor "floating around" — "it has to stay at
    // where it is".
    //
    // It cannot both stay where it is and end up beside the composer; the empty space
    // is the same either way and only its side changes. This chooses staying put, and
    // the space now falls below a short conversation instead of above it. That
    // reverses the earlier reading of "such a big empty space between the end of an
    // answer and the input box" — the same pixels, complained about from the other
    // end — so it is written down here rather than left to be rediscovered.
    function watched() {
        if (!doc.querySelector('.chat-container')) {
            view.__sageWatched = false;
            return false;
        }
        if (isProcessing()) view.__sageWatched = true;
        return !!view.__sageWatched;
    }

    function fill(port) {
        var bar = doc.querySelector('[data-testid="stBottomBlockContainer"]');
        // Not while an answer is coming. A question and a "Reading…" row are short,
        // so this would sit them just above the composer and stream the answer into
        // the bottom of the window with most of the page empty above it — which is
        // where a question goes to be read, not where it goes to be answered. The
        // pin puts it at the top for the duration; this takes over once the answer
        // has landed and its real height is known.
        // `watched()` first, because it is also what records the answer: it has to run
        // on the passes where a turn IS in flight, which are the passes this returns
        // on.
        var seen = watched();
        if (!bar || isProcessing() || !doc.querySelector('.chat-container')) {
            publish('--fill', 0);
            return;
        }
        if (seen) {
            // Where the reader left it. The padding would only move it now.
            publish('--fill', 0);
            return;
        }
        publish('--fill', 0);
        // Reads below force the reflow that makes that zero real.
        if (port.scrollHeight > port.clientHeight + 1) {
            return;   // long enough to scroll on its own; there is no slack
        }
        var end = tail();
        if (end === null) return;
        var slack = composerTop(bar) - end - TAIL_GAP;
        publish('--fill', Math.max(0, Math.min(Math.round(slack), port.clientHeight)));
    }

    // Close the dead space the pin leaves behind once an answer has landed.
    //
    // The pin scrolls so the question sits at the top; if the answer then turns
    // out to be short, the view is left with the reply floating high above the
    // input bar and a screenful of nothing under it.
    //
    // Runs exactly once per answer, keyed off a marker on the parent document so
    // it survives Streamlit rebuilding this script's iframe on every rerun. That
    // matters more than it looks: a version that ran every frame would yank the
    // page back down each time the reader scrolled up to re-read something.
    // A backstop now rather than the mechanism: with the page reserving exactly the
    // bar plus one gap, and `--fill` closing the slack on a short conversation, max
    // scroll already lands the tail one gap above the bar and this finds nothing to
    // do. It stays for the cases neither of those covers — no ResizeObserver, a
    // stylesheet whose padding something else is overriding — so it must still be
    // correct if it ever does fire.
    function settle(el) {
        // A question being edited is still a question, and counting only
        // `.user-message` counted it out of both the stamp and `latest`.
        //
        // The stamp is what makes this run once per turn. Opening the editor takes a
        // bubble off the page and closing it puts one back, so the count changed
        // twice for something that is not a new turn, and each change re-armed a
        // scroll whose whole job is to drag the conversation's tail up against the
        // composer. On a conversation of two turns that lifted the question being
        // edited 218px clean off the top of the window — the reader clicked a pencil
        // and the thing they were editing left the screen. "it has to stay at where
        // it is."
        //
        // `latest` matters for the same reason one line further down: the guard that
        // refuses to buy space by pushing a still-visible question off the top could
        // not see the editor, so on a single-turn conversation it found no question
        // at all and returned early — which is why this only ever showed itself once
        // a second turn existed.
        var slots = doc.querySelectorAll(
            '.user-message, [class*="st-key-edit-box-"]'
        );
        var latest = slots[slots.length - 1];

        // Nothing at all while a question is open for editing.
        //
        // Everything below exists to drag the conversation's tail up against the
        // composer, and a reader who has opened a question three turns back is not
        // looking at the tail. Opening the editor makes the page taller by the
        // difference between a bubble and a text box, which puts the tail under the
        // composer and arms the follow — and the follow then scrolled the thing being
        // edited 218px off the top of the window. Counting the editor as a question,
        // above, was necessary and not sufficient: the follow is keyed on the page's
        // height as well as the turn, and the editor changes that too.
        if (doc.querySelector('[class*="st-key-edit-box-"]')) return;

        var end = tail();
        var bar = doc.querySelector('[data-testid="stBottomBlockContainer"]');
        // Measure before spending the once-per-turn stamp. Spending it up front
        // looked equivalent and was not: this runs on a page Streamlit is still
        // rebuilding, so a pass with no messages in the DOM yet burned the stamp and
        // returned, and the real layout — arriving a moment later with the same
        // count — was never settled. That is the dead space that survived two rounds.
        if (!latest || end === null || !bar) return;

        // Counted on questions, not on answers. An errored turn appends no answer
        // message, so an answer count carries over from the previous turn and this
        // reads as already done; every turn has exactly one question — in one of two
        // forms, which is what `slots` is counting.
        var stamp = String(slots.length);
        var excess = composerTop(bar) - end - TAIL_GAP;

        // The tail is UNDER the composer, not above it, so there is no dead space to
        // close — there is answer hidden behind the input bar, and the rest of this
        // function can only scroll up.
        //
        // How a finished turn gets here: the follow in `autoScroll()` runs only while
        // `#processing-signal` is in the DOM, and that marker belongs to the processing
        // block. The rerun that renders the stored answer appends the Sources strip,
        // the Related list and the rating row — measured at 130–290px — after the last
        // follow has run, and nothing brought the view down over them. The reader was
        // left with the newest answer cut off mid-code-block and its citations and
        // 👍/👎 below the fold, which are the two things this app is built around.
        //
        // Keyed on the page's height as well as the turn, and that is the whole care
        // here. Scrolling does not change `scrollHeight`, so a reader who scrolls up to
        // re-read is never dragged back down — the key still matches and this returns.
        // Content arriving does change it, so a rating row that lands a frame after the
        // strip re-arms the correction exactly once and the tail is followed again.
        if (excess < -4) {
            var reached = stamp + ':' + Math.round(el.scrollHeight / 4);
            if (doc.body.dataset.sageFollowed === reached) return;
            doc.body.dataset.sageFollowed = reached;
            scrollView(el, Math.min(
                Math.max(0, el.scrollHeight - el.clientHeight),
                el.scrollTop - excess
            ));
            return;
        }

        if (doc.body.dataset.sageSettled === stamp) return;
        if (excess <= 4) return;

        // Never buy that space by pushing a still-visible question off the top.
        // Once it has scrolled away on its own there is nothing left to protect.
        var top = latest.getBoundingClientRect().top;
        var move = Math.min(excess, top >= TOP_GAP ? top - TOP_GAP : excess);
        if (move <= 4) return;
        // Stamped here, where it has actually scrolled. Stamped before the two
        // returns above, a pass that found nothing to do would spend the turn's one
        // chance and a later pass with a real gap could not take it.
        doc.body.dataset.sageSettled = stamp;
        scrollView(el, el.scrollTop + move);
    }

    // A landing screen starts at the top. Streamlit keeps the scroll position
    // across a rerun, so arriving at this screen by clearing a conversation left
    // the page parked where that conversation had been: hero off the top of the
    // window, starter cards against the top edge, and nothing on screen to
    // suggest the page had simply not scrolled back. Once per visit to the
    // screen, so it never fights a reader scrolling it themselves.
    function landing(el) {
        if (doc.querySelector('.chat-container')) {
            delete doc.body.dataset.sageAtTop;
            return false;
        }
        if (doc.body.dataset.sageAtTop !== 'done') {
            doc.body.dataset.sageAtTop = 'done';
            if (el.scrollTop > 0) scrollView(el, 0);
        }
        return true;
    }

    // Has the reader taken this turn's page over? Recorded on the parent document
    // rather than in this realm, because Streamlit rebuilds this script's iframe and a
    // flag that died with it would yank them back the moment it did.
    function heldByReader(stamp) {
        return doc.body.dataset.sageHeld === stamp;
    }

    function autoScroll() {
        var el = scroller();
        if (!el) return;
        if (landing(el)) return;
        if (!isProcessing()) {
            chasing = '';
            pinnedAt = -1;
            delete doc.body.dataset.sageHeld;
            settle(el);
            return;
        }

        // Keep the newest text on screen while the answer arrives. NOT "bring the
        // question to the top of the viewport": that is what this comment used to
        // claim, and it has not been true since the two-rule version below was
        // reverted. `TOP_GAP` survives only in `settle()` now, as a guard against
        // buying space by pushing a still-visible question off the top.
        //
        // Asked for again on 2026-08-28 — a follow-up leaves the previous answer
        // filling the screen above it, which is real and is the cost of the rule
        // below — and declined, with the reasoning recorded here so it is not
        // re-litigated from scratch. Putting a question at the top of the window needs
        // a viewport of content beneath it, and at send time there is none: the page
        // reserves only the measured bar height plus `--tail-gap`, so the scroll clamps
        // at `limit` and the question lands at an arbitrary height. Doing it properly
        // means reserving a screen of space under the newest question for the length of
        // the turn, which changes `scrollHeight` twice more per turn precisely where
        // `settle()` spends its two once-per-turn stamps — the stamps that exist
        // because a pass running mid-rebuild burned the turn's one chance — and which
        // `render_check.py` would read as dead space above the input bar. The bound it
        // would fail is the only thing standing between that design and a screen of
        // blank space nobody notices for a day.
        //
        // The rule that is here never freezes the page, which is the property the
        // reverted version lost. That was judged worth more than the screen a
        // previous answer occupies.
        //
        // This used to pin to the document's absolute bottom on every frame. On
        // anything but a tall window that scrolls the question clean off the top —
        // and because the container reserves the measured bar height plus
        // `--tail-gap` below the last message to clear the fixed input, the bottom
        // of the document is mostly empty padding, so pinning there wasted a
        // third of the viewport on blank space.
        var messages = doc.querySelectorAll('.user-message');
        var latest = messages[messages.length - 1];
        if (!latest) return;

        // A new question starts a new chase, so nothing below reads a position — or a
        // hand-off — left over from the previous turn.
        var stamp = String(messages.length);
        if (chasing !== stamp) {
            chasing = stamp;
            pinnedAt = -1;
            delete doc.body.dataset.sageHeld;
        }

        var limit = Math.max(0, el.scrollHeight - el.clientHeight);
        // Has the reader scrolled away from where this script left the view? Then the
        // page is theirs for the rest of the turn.
        //
        // Compared against the position CLAMPED to what the page can still offer, not
        // against the raw one. A page that shrinks takes the scroll down with it — the
        // tool round that wipes what streamed and starts the answer again does exactly
        // that — and reading the browser's clamp as a reader would hand the turn over
        // on a move nobody made, leaving the real answer to arrive below the fold.
        //
        // Either direction counts. While the chase is running there is no downward move
        // to make — it leaves the view at the bottom of the page every pass — so a
        // reader who has gone down is one who has gone down from the pinned question,
        // to read the tail, and scrolling them back up to it is the same rudeness as
        // dragging them forward.
        if (pinnedAt >= 0
                && Math.abs(el.scrollTop - Math.min(pinnedAt, limit)) > 4) {
            doc.body.dataset.sageHeld = stamp;
        }
        if (heldByReader(stamp)) return;

        // Keep the newest text on screen for as long as the answer is arriving, and
        // scroll DOWN only. One rule for the whole turn, deliberately.
        //
        // It used to be two: follow the page while it was too short to lift the question
        // to the top of the window, then stop there for the rest of the turn. That read
        // as the page freezing — the view arrived on send and every token after the first
        // screenful streamed in below the fold with nothing moving. Reinstating the
        // follow *alongside* the pin is worse than either: the follow scrolls down to the
        // tail, the pin pulls back up to the question, and they fight every pass.
        //
        // The target is the tail rather than the document's end, because the container
        // reserves the measured bar height plus `--tail-gap` below the last message to
        // clear the fixed composer — the bottom of the document is mostly padding, and
        // scrolling there wastes a third of the window on nothing. Where the reply
        // actually ends, one gap above the composer, is the same edge `settle()` closes
        // to once the turn is over.
        //
        // Down only, so a reply that already fits is never yanked, and the question ends
        // up on screen without being pinned there: at the start of a turn the tail IS
        // just below the question. A reply longer than the window stays the reader's to
        // scroll — the moment they move it, the hand-off above sees that and this stops
        // for the rest of the turn.
        var bar = doc.querySelector('[data-testid="stBottomBlockContainer"]');
        var end = tail();
        if (!bar || end === null) return;
        var hidden = end - (composerTop(bar) - TAIL_GAP);
        if (hidden <= 2) return;
        scrollView(el, Math.min(limit, el.scrollTop + hidden));
        // Read back rather than assumed. The scroller refuses while Streamlit is
        // mid-rebuild, and `scroll-behavior: smooth` anywhere in the chain turns the
        // assignment into an animation that has not started yet — in both cases the
        // view is still where it was, and recording the intended position instead
        // would read as the reader having moved it on the very next pass.
        pinnedAt = el.scrollTop;
    }

    /* --- light or dark, whichever the reader asked for ------------------- */
    //
    // Two halves have to agree, and only one of them is this file's.
    //
    // `static/app.css` carries both palettes and picks between them on
    // `prefers-color-scheme` — the browser's setting — so a stylesheet cannot be told
    // to use the other one. Streamlit paints the page around it (the background, the
    // body text, every widget's chrome) from a theme resolved in React from
    // `window.matchMedia`, which nothing here can reach either. Repainting one without
    // the other is the exact bug `.streamlit/config.toml` was written to fix: the dark
    // palette on a white page, source links at 1.9:1.
    //
    // So the choice is applied twice from one place. An attribute on <html> switches
    // the stylesheet, which is a plain attribute selector and works in anything. And
    // `matchMedia` is wrapped so that a question about the colour scheme answers with
    // the choice — after which Streamlit only has to be asked to resolve its theme
    // again, which it does on `afterprint` (it re-reads the preference when a page
    // comes back from the printer). No reload, so the conversation survives; nothing
    // is sent to Python, so this works while an answer is streaming.
    //
    // The choice itself lives in localStorage, not in session state, for the same
    // reason: a Streamlit widget click is a rerun, and a rerun during a turn aborts
    // it. It also means the choice outlives the session, which is what a reader
    // expects of a theme.
    //
    // If a future Streamlit stops listening for `afterprint`, `enforceTheme` gives up
    // after a few tries and the stylesheet's own palette carries the page — the
    // reader gets our colours on Streamlit's default background rather than a broken
    // toggle. That is the reason app.css states both palettes itself instead of
    // leaning on the host.
    var THEME_KEY = 'sage-theme';
    var THEME_CYCLE = ['system', 'light', 'dark'];

    // A hand-drawn set rather than emoji: ☀️/🌙 render as a different size, weight and
    // colour in every browser, and this button sits in a row of 14px line icons.
    var SUN_SVG = '<svg aria-hidden="true" focusable="false" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"></circle><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M6.3 17.7l-1.4 1.4M19.1 4.9l-1.4 1.4"></path></svg>';
    var MOON_SVG = '<svg aria-hidden="true" focusable="false" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8"></path></svg>';
    var AUTO_SVG = '<svg aria-hidden="true" focusable="false" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"></circle><path d="M12 3a9 9 0 0 0 0 18z" fill="currentColor" stroke="none"></path></svg>';

    var THEME_ICON = {system: AUTO_SVG, light: SUN_SVG, dark: MOON_SVG};
    var THEME_TITLE = {
        system: 'Theme: following your browser — switch to light',
        light: 'Theme: light — switch to dark',
        dark: 'Theme: dark — follow your browser again'
    };

    // The choice, and where it lives — which is two places for one reason.
    //
    // `view.__sageTheme` is the authority for this visit. It has to be: localStorage is
    // refusable (private mode, a browser configured against it, an embedded frame) and
    // when it is refused the READ throws too, not only the write. Keyed off storage
    // alone, every rerun read `null`, decided the choice was `system`, and painted the
    // icon accordingly — so the button lied about its own state and the theme came
    // undone a moment after being set. Measured in a context with storage denied:
    // `attr: light`, `painted: system`.
    //
    // localStorage is what carries the choice to the NEXT visit, and nothing more. If
    // it is unavailable the toggle still works; it just forgets between visits.
    function themeChoice() {
        var held = view.__sageTheme;
        if (THEME_CYCLE.indexOf(held) !== -1) return held;
        var stored = null;
        try { stored = view.localStorage.getItem(THEME_KEY); } catch (err) { stored = null; }
        return THEME_CYCLE.indexOf(stored) === -1 ? 'system' : stored;
    }

    function storeTheme(choice) {
        view.__sageTheme = choice;
        try { view.localStorage.setItem(THEME_KEY, choice); } catch (err) { /* this visit only */ }
    }

    // The browser's own answer, never the wrapped one below.
    function systemScheme() {
        var real = view.__sageRealMM;
        try {
            var mql = real ? real('(prefers-color-scheme: dark)')
                           : view.matchMedia('(prefers-color-scheme: dark)');
            return mql && mql.matches ? 'dark' : 'light';
        } catch (err) { return 'light'; }
    }

    // Answer a colour-scheme question with the reader's choice, and leave every other
    // media query alone — `useViewportSize` asks this same function about widths.
    //
    // A plain object rather than the real MediaQueryList with `matches` overwritten:
    // that property is read-only. add/removeEventListener forward to the real list, so
    // a reader on `system` is still followed when they change their OS setting.
    // Re-wrapped on every run, not wrapped once. The wrapper is a closure defined in
    // THIS script's realm, and Streamlit destroys and rebuilds the iframe the script is
    // served in on every rerun — so a wrapper installed on the parent window by the
    // first copy of this file belongs, from the second rerun onwards, to a document
    // that no longer exists. Chromium goes on calling it; that is not a guarantee
    // worth resting a reader's colour scheme on across every browser. The ORIGINAL
    // `matchMedia` is kept on the parent and reused, so only ever one layer deep
    // however many times this runs.
    function wrapMatchMedia() {
        if (!view.matchMedia) return;
        var real = view.__sageRealMM || view.matchMedia.bind(view);
        view.__sageRealMM = real;
        view.matchMedia = function (query) {
            var mql = real(query);
            var want = view.__sageScheme;
            var text = String(query);
            if (!want || text.indexOf('prefers-color-scheme') === -1) return mql;
            var asked = text.indexOf('dark') !== -1 ? 'dark'
                      : text.indexOf('light') !== -1 ? 'light' : '';
            if (!asked) return mql;   // no-preference, or something we do not model
            return {
                media: mql.media,
                matches: asked === want,
                onchange: null,
                addListener: function (fn) {
                    try { mql.addListener(fn); } catch (err) { /* removed API */ }
                },
                removeListener: function (fn) {
                    try { mql.removeListener(fn); } catch (err) { /* removed API */ }
                },
                addEventListener: function (kind, fn, options) {
                    try { mql.addEventListener(kind, fn, options); } catch (err) { /* ignored */ }
                },
                removeEventListener: function (kind, fn, options) {
                    try { mql.removeEventListener(kind, fn, options); } catch (err) { /* ignored */ }
                },
                dispatchEvent: function () { return false; }
            };
        };
    }

    // Ask Streamlit to resolve its theme again. It listens for `afterprint` in order
    // to come back from a printed page, and re-reads the colour-scheme preference when
    // it does — which by then is the wrapper above.
    function nudgeHost() {
        try { view.dispatchEvent(new view.Event('afterprint')); } catch (err) { /* ignored */ }
    }

    // What Streamlit is ACTUALLY painting, read off the page. Its theme lives in React
    // state that nothing here can see, and the page background is the one part of it
    // that is always painted and always visible.
    function hostScheme() {
        var nodes = [doc.querySelector('.stApp'), doc.body];
        for (var i = 0; i < nodes.length; i++) {
            if (!nodes[i]) continue;
            var parts = String(view.getComputedStyle(nodes[i]).backgroundColor || '')
                .replace(/[^0-9.,]/g, '').split(',');
            if (parts.length < 3) continue;
            // Transparent tells us nothing about what the reader sees; try the next.
            if (parts.length > 3 && parseFloat(parts[3]) === 0) continue;
            var light = (0.2126 * parseFloat(parts[0])
                       + 0.7152 * parseFloat(parts[1])
                       + 0.0722 * parseFloat(parts[2])) / 255;
            return light > 0.5 ? 'light' : 'dark';
        }
        return '';
    }

    // Which scheme the page should be in. `null` for `system` means "whatever the
    // browser says", which is a question only the unwrapped `matchMedia` can answer.
    function wantedScheme() {
        return view.__sageScheme || systemScheme();
    }

    function applyTheme(choice) {
        var scheme = choice === 'system' ? '' : choice;
        wrapMatchMedia();
        view.__sageScheme = scheme || null;
        if (scheme) doc.documentElement.setAttribute('data-sage-theme', scheme);
        else doc.documentElement.removeAttribute('data-sage-theme');
        view.__sageNudges = 0;
        // Only when the page is not already in it. This runs on every rerun, because
        // Streamlit rebuilds the iframe this script is served in — and each nudge is a
        // React state update carrying a freshly built theme object, which compares
        // unequal to the current one however identical it is. Nudging unconditionally
        // therefore re-rendered the whole app once per rerun for no change at all.
        if (hostScheme() !== wantedScheme()) nudgeHost();
    }

    // The nudge above can arrive before the React effect that listens for it — this
    // script is an iframe on a page that is still mounting — and an event nobody is
    // listening for is silently lost. So the wanted scheme is checked against what the
    // page is painted with on every pass, and re-asked for if they disagree. Bounded,
    // because a build that has stopped listening would otherwise be asked for ever.
    //
    // Asked about `system` too, not only about an explicit choice. Going BACK to
    // `system` is the case that needs it most: unwrapping `matchMedia` tells the
    // stylesheet to follow the browser again, but Streamlit is still holding the theme
    // it was last told to use, so a reader who turned dark off on a light device was
    // left with the light palette on a near-black page — the same mismatch
    // `.streamlit/config.toml` exists to prevent, arrived at from the other side.
    function enforceTheme() {
        var have = hostScheme();
        if (!have || have === wantedScheme()) { view.__sageNudges = 0; return; }
        var tries = view.__sageNudges || 0;
        if (tries >= 8) return;
        view.__sageNudges = tries + 1;
        nudgeHost();
    }

    function paintToggle(btn, choice) {
        if (btn.dataset.sageTheme === choice) return;
        btn.dataset.sageTheme = choice;
        btn.innerHTML = THEME_ICON[choice];
        btn.title = THEME_TITLE[choice];
        btn.setAttribute('aria-label', btn.title);
    }

    // Where the toggle goes, and this is the part of it with a history.
    //
    // Top of the page, which in this app is Streamlit's own 60px header band — and
    // putting anything there has gone wrong three times, all of them measured:
    //
    // * `[data-testid="stHeader"]` is transparent and sits at z-index 999990, so an
    //   element merely placed in that band is painted over and takes no clicks. That is
    //   the bug app.css records against the old `top: 8px` controls row: on screen,
    //   completely dead. A `position: fixed` button appended to the header does not
    //   escape it either — `stToolbar` carries that z-index explicitly and outranks a
    //   child of the header at `z-index: auto`.
    // * Appending INSIDE `stToolbar` does take clicks. It is still the wrong home:
    //   Streamlit removes the whole toolbar from the document when the sidebar is
    //   expanded, so the toggle disappeared every time the panel was opened.
    // * Placing it from a measured offset past Streamlit's sidebar arrow — on the LEFT —
    //   was the last mistake, and the reader reported it as "very unstable". Closing the
    //   panel puts that arrow back while the panel is still sliding out, so the
    //   measurement lands at x≈300 instead of x≈18, and nothing corrects it afterwards
    //   because `sync()` stops running on a page with nothing left to mutate. Measured:
    //   `--toggle-left` went 56px → 356px on the first open-and-close and stayed there.
    //
    // It is in the top-RIGHT corner now, beside the Share button, which is where the
    // reader asked for it — and that corner is also the stable one. Streamlit's header
    // shrinks from the left when the panel opens (measured: 1280 wide becomes
    // `[300, 0, 980, 60]`), so its right edge does not move and neither does anything
    // anchored to it. Nothing on the right animates, which is the whole reason the left
    // anchor could not be trusted.
    //
    // So it hangs off <body>, which cannot be rebuilt out from under it, and app.css
    // pins it at a z-index that outranks the chrome — exactly what the strip of controls
    // under the input already does at the other end of the page.
    //
    // REBUILT ONCE PER RUN of this script, and that is the whole of the "the toggle
    // doesn't work at all" bug. Streamlit destroys and rebuilds the iframe this file is
    // served in on every rerun. A click listener added by the first copy is a closure
    // belonging to that copy's realm, and once the realm is gone the listener never
    // fires again — the button is still there, still on top, still hit-tests as itself,
    // and does nothing. It worked for exactly one click, before the first rerun.
    // Keeping the node and adding a fresh listener has the same problem, because the
    // listener is the part that goes stale, so the node is replaced.
    //
    // `built` is a plain closure variable, so it is false again in each new copy of this
    // script and true for the rest of that copy's syncs: one rebuild per rerun rather
    // than one per mutation frame.
    var built = false;

    // How far from the right edge, so the button lands NEXT TO the host's own controls
    // rather than on top of them. `Share` is a host toolbar item — Community Cloud sends
    // it over the host-communication channel and Streamlit renders it into
    // `stToolbarActions` — so it does not exist on a local run, and its width is not
    // something this repo can know. It is measured instead: sit just left of the
    // leftmost thing in the header's right-hand group, or in the corner when there is
    // nothing there.
    //
    // The value only ever grows. Streamlit rebuilds the header as the panel opens and
    // closes, and for a frame or two those controls are absent — read at face value that
    // would snap the button into the corner and back, which is the instability this
    // placement exists to end. Once a Share button has been seen, the room reserved for
    // it stays reserved.
    var RIGHT_CONTROLS = [
        '[data-testid="stToolbarActions"]',
        '[data-testid="stAppDeployButton"]',
        '[data-testid="stMainMenu"]'
    ];
    var TOGGLE_RIGHT_MIN = 16;

    function publishToggleRight() {
        var edge = 0;
        RIGHT_CONTROLS.forEach(function (selector) {
            doc.querySelectorAll(selector).forEach(function (node) {
                var rect = node.getBoundingClientRect();
                if (rect.width <= 0 || rect.height <= 0) return;
                var room = Math.round(view.innerWidth - rect.left) + 8;
                if (room > edge) edge = room;
            });
        });
        var want = Math.max(TOGGLE_RIGHT_MIN, edge);
        if (want < (view.__sageToggleRight || 0)) return;   // never creep leftward
        view.__sageToggleRight = want;
        publish('--toggle-right', want);
    }

    function addThemeToggle() {
        publishToggleRight();
        var existing = doc.getElementById('theme-toggle');
        if (built && existing && existing.parentElement === doc.body) {
            paintToggle(existing, themeChoice());
            return;
        }
        if (existing) existing.remove();

        var btn = injected('button');
        btn.id = 'theme-toggle';
        btn.type = 'button';
        btn.addEventListener('click', function (event) {
            event.preventDefault();
            event.stopPropagation();
            var next = THEME_CYCLE[
                (THEME_CYCLE.indexOf(themeChoice()) + 1) % THEME_CYCLE.length
            ];
            storeTheme(next);
            applyTheme(next);
            paintToggle(btn, next);
        });
        paintToggle(btn, themeChoice());
        doc.body.appendChild(btn);
        built = true;
    }

    /* --- the arrows that open and close the panel ------------------------ */

    // Streamlit draws them and leaves them unlabelled — `aria-label=""` on the one in
    // the header, nothing at all on the one in the panel — so the only thing saying
    // what either does is a double-chevron pointing somewhere. Hovering told a reader
    // nothing and a screen reader read out "button".
    //
    // Both are relabelled on every pass rather than once, because each exists only in
    // one of the two states: the header's arrow is removed from the document when the
    // panel opens and rebuilt when it closes.
    var PANEL_LABELS = [
        ['stExpandSidebarButton', 'Show sidebar'],
        ['stSidebarCollapseButton', 'Hide sidebar']
    ];

    function label(btn, text) {
        if (!btn || btn.title === text) return;
        btn.title = text;
        btn.setAttribute('aria-label', text);
    }

    function labelPanelToggles() {
        PANEL_LABELS.forEach(function (pair) {
            var host = doc.querySelector('[data-testid="' + pair[0] + '"]');
            if (!host) return;
            // One of the two IS the button; the other is a div wrapping one.
            label(host.tagName === 'BUTTON' ? host : host.querySelector('button'),
                  pair[1]);
        });
    }

    // And the ✕ on each conversation in the panel, which is a glyph and nothing else.
    //
    // Done here rather than with Streamlit's `help=`, which was tried first: its
    // tooltip is a black panel beside the cursor, and on a 240px row it covered the
    // row above — the one thing a reader needs to see while deciding whether to delete
    // this one. It also renders a second, zero-sized copy of the button inside the
    // tooltip's wrapper. A `title` is a small native tooltip, and `aria-label` is the
    // accessible name a lone ✕ has no other way of getting.
    //
    function labelChatActions() {
        doc.querySelectorAll('[class*="st-key-chat-act-"] button').forEach(function (btn) {
            // "chat", not "conversation": the button above the list says New chat, and
            // an action that changes its noun halfway through is one a reader has to
            // re-learn.
            label(btn, 'Delete this chat');
        });
    }

    /* --- injected controls ---------------------------------------------- */

    function addPaperclip() {
        var input = doc.querySelector('[data-testid="stChatInput"]');
        if (!input || doc.getElementById('paperclip-btn')) return;

        var btn = injected('button');
        btn.id = 'paperclip-btn';
        btn.type = 'button';
        btn.innerHTML = CLIP_SVG;
        // Deliberately not a list of extensions. It was one — "PDF, TXT, MD, PY,
        // JSON, CSV, YAML" — and it went stale the moment uploads stopped being
        // gated on a list at all: anything that reads as text is accepted now, and a
        // tooltip enumerating seven of them reads as a refusal of the rest.
        btn.title = 'Attach a PDF or text file — script, log, config, source';
        btn.setAttribute('aria-label', btn.title);
        btn.addEventListener('click', function (event) {
            event.preventDefault();
            event.stopPropagation();
            var file = doc.querySelector('[data-testid="stFileUploader"] input[type="file"]');
            if (file) file.click();
        });

        input.style.position = 'relative';
        input.insertBefore(btn, input.firstChild);
    }

    /* --- files from outside the page -------------------------------------- */

    // Streamlit's file uploader is the only door into app.py's attachment pipeline,
    // and app.css clips that widget to 1×1px because uploads are driven from the
    // paperclip in the composer instead. So every other way of offering a file — the
    // paperclip's own `click()`, a pasted screenshot, a drag from the desktop — has to
    // end at this one `<input>`.
    function uploaderInput() {
        return doc.querySelector('[data-testid="stFileUploader"] input[type="file"]');
    }

    // Put files on that input as if the widget's own dropzone had taken them.
    //
    // The transfer has to go through `DataTransfer`, because `input.files` is not
    // otherwise assignable, and the `change` has to be dispatched by hand: React
    // listens for the native event at the document root, so a bubbling one reaches
    // its handler, but nothing dispatches it when the list is set programmatically.
    //
    // `view.DataTransfer` rather than this iframe's, because the files come from the
    // parent realm and the widget reading them lives there too.
    function handToUploader(files) {
        var target = uploaderInput();
        if (!target) return false;
        var transfer = new view.DataTransfer();
        // Seeded with what the widget already holds, because assigning `input.files`
        // REPLACES the list. Without this, offering one file silently dropped every
        // file picked before it from the widget's own record — the chips stayed, so
        // nothing looked wrong.
        for (var f = 0; f < (target.files || []).length; f++) {
            transfer.items.add(target.files[f]);
        }
        for (var i = 0; i < files.length; i++) transfer.items.add(files[i]);
        target.files = transfer.files;
        target.dispatchEvent(new view.Event('change', {bubbles: true}));
        return true;
    }

    // Paste a screenshot into the box and have it attach.
    //
    // Before this, nothing happened at all: the clipboard's image never reached
    // Streamlit's uploader, because the only thing wired to that uploader was the
    // paperclip's `click()`. A paste is the same file arriving by a different door,
    // so it is handed to the same input.
    // Distinguishes one paste from the next. Two screenshots of the same size would
    // otherwise be the same (name, size) pair and count as one attachment.
    var pasteCount = 1;

    // Re-registered every pass, with the previous registration torn down first.
    //
    // The guard used to be a `data-` marker on the parent's own node, and that was
    // wrong in a way with no visible symptom: the marker lives in the parent document
    // and survives, while the listener lives in THIS iframe's realm and dies whenever
    // Streamlit rebuilds the component. The next copy of the script saw the marker,
    // skipped registration, and no listener existed anywhere — so pasting a screenshot
    // worked once per page load and silently never again. A remover parked on the
    // parent window is the one handle that outlives the realm it came from.
    function addPasteHandler() {
        var input = doc.querySelector('[data-testid="stChatInput"]');
        if (!input) return;
        if (view.__sagePasteOff) {
            try { view.__sagePasteOff(); } catch (err) { /* node already gone */ }
        }
        var onPaste = function (event) {
            var data = event.clipboardData;
            if (!data) return;
            // Text wins. A clipboard from Word, Excel, Sheets or Preview carries
            // text/plain AND an image, and taking the file branch on those pasted a
            // screenshot of the selection while throwing the text away.
            var types = data.types ? [].slice.call(data.types) : [];
            if (types.indexOf('text/plain') !== -1) return;
            var files = [];
            // `items` rather than `files`: a screenshot on the clipboard is an item
            // of kind 'file' and shows up in both, but some browsers only populate
            // `items` for synthesised image data.
            for (var i = 0; i < (data.items || []).length; i++) {
                var item = data.items[i];
                if (item.kind === 'file') {
                    var file = item.getAsFile();
                    if (file) files.push(file);
                }
            }
            if (!files.length) return;
            // The uploader is looked up BEFORE the paste is cancelled. The other order
            // meant that when the input was missing — mid-rebuild, or the widget key
            // being swapped — the paste was swallowed and nothing happened at all.
            if (!uploaderInput()) return;
            event.preventDefault();
            var stamped = files.map(function (file, index) {
                // A clipboard image arrives as "image.png" or with no name at all, so
                // several pastes would collide on the (name, size) pair app.py
                // identifies a file by — two screenshots of the same size would be one
                // attachment. The index makes them distinct, which the comment here
                // claimed before the code did it.
                var stamp = pasteCount + (index ? '-' + index : '');
                var name = file.name
                    ? file.name.replace(/(\.[^.]*)?$/, '-' + stamp + '$1')
                    : 'pasted-image-' + stamp + '.png';
                return new view.File([file], name, {type: file.type});
            });
            pasteCount += 1;
            handToUploader(stamped);
        };
        input.addEventListener('paste', onPaste);
        view.__sagePasteOff = function () {
            input.removeEventListener('paste', onPaste);
        };
    }

    // Drag a file onto the page and have it attach.
    //
    // Reported as "no reaction at all", and it was both halves of that: nothing while
    // the file was over the box, and nothing attached when it was let go. Streamlit's
    // uploader does have a dropzone of its own — `stFileUploaderDropzone`, inside the
    // widget — and app.css clips that widget to a single pixel, because uploads here
    // are driven from the paperclip. So the only place on the page that would take a
    // dropped file was one pixel wide and invisible.
    //
    // These listeners are on the document rather than on the composer, which is the
    // part worth stating: the browser's default action for a file dropped on a page is
    // to NAVIGATE to that file, so a drop that missed the 56px-tall box at the bottom
    // of the window did not merely fail — it replaced the conversation with a picture
    // of the file. Cancelling that everywhere is the same line that lets the drop
    // land, so the page takes a file dropped anywhere and aims all of them at the
    // composer. The composer is what lights up, because that is where the file is
    // going and where its chip will appear.

    // Does this drag carry files? `types`, not `items` or `files`: for a drag from
    // outside the page, browsers withhold the file list until the drop, so a
    // `dragover` that asked how many files there were would answer none every time and
    // never light the composer up. 'Files' is in `types` for the whole drag.
    function dragHasFiles(transfer) {
        if (!transfer) return false;
        var types = transfer.types ? [].slice.call(transfer.types) : [];
        return types.indexOf('Files') !== -1;
    }

    // Cleared on the drop and when the drag leaves the window — plus a timer, because
    // neither of those is guaranteed to arrive. A drag cancelled with Escape, or
    // released over another window, fires no `dragleave` here, and the composer would
    // stay lit for the rest of the session. `dragover` repeats several times a second
    // while a drag is over the page, so one that has gone quiet means the drag is over.
    // The handle lives on the parent window, not in this closure, for the same reason
    // the removers do: a rerun lands a second copy of this script on the page, and a
    // timer only the previous copy can see is one that fires against a drag the current
    // copy is in the middle of — the box goes dark mid-drag and stays that way until the
    // next `dragover` puts it back.
    function dropTarget(on) {
        if (view.__sageDragTimer) view.clearTimeout(view.__sageDragTimer);
        view.__sageDragTimer = 0;
        if (!on) {
            delete doc.body.dataset.sageDropping;
            return;
        }
        doc.body.dataset.sageDropping = 'true';
        view.__sageDragTimer = view.setTimeout(function () { dropTarget(false); }, 900);
    }

    // A drop that lands while Streamlit is rebuilding finds no uploader for a frame or
    // two — and mid-answer the DOM mutates once per token, which is exactly when
    // someone drops a file to ask about it next. `File` objects stay valid after the
    // handler returns, so the drop waits for the widget instead of being lost to the
    // same silence this whole section is here to fix. Parked on the parent's timer,
    // which outlives the rebuild that took the widget away.
    function handWhenReady(files, tries) {
        if (handToUploader(files) || tries <= 0) return;
        view.setTimeout(function () { handWhenReady(files, tries - 1); }, 100);
    }

    // Re-registered every pass with the previous registration torn down first, and the
    // remover parked on the parent window — for the reason spelled out above
    // `addPasteHandler`. A `data-` marker on the parent's DOM would survive the
    // rebuild that kills the listener, so dropping a file would work once per page
    // load and then silently never again.
    function addDropHandler() {
        if (view.__sageDropOff) {
            try { view.__sageDropOff(); } catch (err) { /* realm already gone */ }
        }
        // Streamlit's own dropzone is still in there, one pixel of it. A drop that
        // manages to hit it is React's to handle, and taking it here as well would
        // attach the file twice.
        var streamlits = function (event) {
            var node = event.target;
            return !!(node && node.closest
                && node.closest('[data-testid="stFileUploader"]'));
        };
        var onOver = function (event) {
            if (!dragHasFiles(event.dataTransfer) || streamlits(event)) return;
            // Required on every `dragover`, or no `drop` is ever delivered.
            // `dropEffect` is what makes the cursor a copy arrow rather than the
            // "not allowed" circle while the file is over the page.
            event.preventDefault();
            try { event.dataTransfer.dropEffect = 'copy'; } catch (err) { /* frozen */ }
            dropTarget(true);
        };
        var onLeave = function (event) {
            // `dragleave` fires at every element boundary the pointer crosses, so a
            // drag moving *across* the page reports leaving it several times a second.
            // The one with nothing on the other side is the pointer leaving the window.
            if (event.relatedTarget) return;
            dropTarget(false);
        };
        var onDrop = function (event) {
            if (!dragHasFiles(event.dataTransfer) || streamlits(event)) return;
            // First and unconditionally: every line below can decline the file, and the
            // default action for one that gets away is to navigate away from the app.
            event.preventDefault();
            dropTarget(false);
            var files = [].slice.call(event.dataTransfer.files || []);
            // A dropped folder arrives as a `File` the browser cannot read, and handing
            // one to the uploader fails inside a widget nobody can see. `items` is
            // neutered the moment this handler returns, so the question is asked now
            // and matched by name — `items` also holds non-file entries, so its indices
            // are not `files`' indices.
            var items = event.dataTransfer.items || [];
            var folders = {};
            for (var i = 0; i < items.length; i++) {
                var entry = items[i].webkitGetAsEntry && items[i].webkitGetAsEntry();
                if (entry && entry.isDirectory) folders[entry.name] = true;
            }
            files = files.filter(function (file) { return !folders[file.name]; });
            if (!files.length) return;
            handWhenReady(files, 20);
            // What anyone does next is type the question about the file they dropped.
            var area = doc.querySelector('textarea[data-testid="stChatInputTextArea"]');
            if (area) area.focus();
        };
        var onEnd = function () { dropTarget(false); };
        doc.addEventListener('dragenter', onOver);
        doc.addEventListener('dragover', onOver);
        doc.addEventListener('dragleave', onLeave);
        doc.addEventListener('dragend', onEnd);
        doc.addEventListener('drop', onDrop);
        view.__sageDropOff = function () {
            doc.removeEventListener('dragenter', onOver);
            doc.removeEventListener('dragover', onOver);
            doc.removeEventListener('dragleave', onLeave);
            doc.removeEventListener('dragend', onEnd);
            doc.removeEventListener('drop', onDrop);
        };
    }

    // Up-arrow recalls what you asked before, the way a shell does.
    //
    // The questions are read out of the page rather than passed in from Python: they
    // are already in the DOM as `.user-bubble`, one per turn, in order, so there is
    // nothing to keep in sync and nothing to serialise. `history` is rebuilt on every
    // keypress for the same reason — a rerun replaces those nodes, and a list captured
    // once would recall a conversation that has since been cleared.
    //
    // Hijacked ONLY when the caret is at the very start of the box and there is no
    // selection. Anywhere else, Up means "move up a line", and a multi-line question
    // being retyped is exactly when stealing that would be most annoying.
    // Puts a value into a React-controlled field so React believes it.
    //
    // Assigning `.value` directly does not work: React caches the last value it wrote
    // on the node and compares against it, so a plain assignment plus an `input` event
    // is discarded as "no change". The field then LOOKS updated — the text is on
    // screen — while Streamlit still holds the old value, which is why a recalled
    // prompt could not be sent until something was typed after it: the send button
    // stayed disabled because, as far as Streamlit knew, the box was still empty.
    //
    // Going through the prototype's own setter is what React's value tracker hooks,
    // so the change is seen and the widget updates.
    function setFieldValue(field, text) {
        var proto = view.HTMLTextAreaElement && view.HTMLTextAreaElement.prototype;
        var descriptor = proto
            ? Object.getOwnPropertyDescriptor(proto, 'value')
            : null;
        if (descriptor && descriptor.set) {
            descriptor.set.call(field, text);
        } else {
            field.value = text;   // no prototype setter: better than nothing
        }
        field.dispatchEvent(new view.Event('input', {bubbles: true}));
    }

    // What the reader has already asked, most recent first.
    //
    // Read from the page rather than passed in from Python: the questions are already
    // in the DOM, one `.user-bubble` per turn. Attachment badges are nested INSIDE
    // that bubble, and `textContent` concatenates without a separator, so the raw
    // reading of a turn with a file on it came out as
    // "🖼️ pasted-image-1.pngHow do I read this log?" — the filename recalled into the
    // box as if it had been typed. The badges are removed from a clone instead.
    function askedBefore() {
        var out = [];
        doc.querySelectorAll('.user-bubble').forEach(function (node) {
            var copy = node.cloneNode(true);
            copy.querySelectorAll('.attachment-badge').forEach(function (badge) {
                badge.remove();
            });
            var text = copy.textContent.replace(/^\s+|\s+$/g, '');
            if (text) out.push(text);
        });
        return out.reverse();
    }

    // Up recalls what you asked before; Down comes back toward the present and, one
    // step past the newest question, leaves the box as it found it.
    //
    // The browse position lives on the PARENT window, not in this closure. sync()
    // rebuilds these handlers on every mutation frame, so a closure variable was reset
    // by any DOM change between two keypresses — which made repeated Up stick on the
    // most recent question instead of walking back through the conversation.
    function addPromptHistory() {
        var box = doc.querySelector('.stChatInput textarea');
        if (!box) return;
        if (view.__sageHistoryOff) {
            try { view.__sageHistoryOff(); } catch (err) { /* node gone */ }
        }
        if (typeof view.__sageHistoryAt !== 'number') view.__sageHistoryAt = -1;

        var onKey = function (event) {
            if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return;
            // Never mid-composition: the arrow keys belong to the IME while a Chinese,
            // Japanese or Korean candidate is being chosen.
            if (event.isComposing) return;
            var at = view.__sageHistoryAt;
            // Up only from the very start of the box, so it still moves the caret in a
            // multi-line question. Once browsing, both keys are ours.
            var atStart = box.selectionStart === 0 && box.selectionEnd === 0;
            if (event.key === 'ArrowUp' && at === -1 && !atStart) return;
            if (event.key === 'ArrowDown' && at === -1) return;

            var asked = askedBefore();
            if (!asked.length) return;

            if (event.key === 'ArrowUp') {
                if (at === -1) view.__sageHistoryDraft = box.value;
                if (at + 1 >= asked.length) { event.preventDefault(); return; }
                view.__sageHistoryAt = at + 1;
            } else {
                // Down always advances toward the present, even after the recalled
                // question has been edited. Editing used to end the browse, which left
                // Down doing nothing at all — the reader was stuck on a prompt they had
                // changed with no way forward.
                view.__sageHistoryAt = at - 1;
            }
            event.preventDefault();
            var next = view.__sageHistoryAt;
            // Past the newest question: back to whatever was in the box before the
            // first Up, which is empty in the ordinary case.
            var text = next === -1 ? (view.__sageHistoryDraft || '') : asked[next];
            setFieldValue(box, text);
            box.selectionStart = box.selectionEnd = text.length;
            box.style.height = 'auto';
        };

        // Sending resets the browse: the next Up starts from the newest question
        // rather than from wherever the last walk stopped.
        var onSubmit = function (event) {
            if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
                view.__sageHistoryAt = -1;
                view.__sageHistoryDraft = '';
            }
        };

        box.addEventListener('keydown', onKey);
        box.addEventListener('keydown', onSubmit);
        view.__sageHistoryOff = function () {
            box.removeEventListener('keydown', onKey);
            box.removeEventListener('keydown', onSubmit);
        };
    }

    // Empty the composer when the conversation is cleared.
    //
    // Clearing wipes the transcript from Python, but the text in Streamlit's chat input
    // is client-side state that Python only ever reads on submit — so the last question
    // stayed in the box, sitting over the starter cards on a freshly emptied landing
    // screen as though it were still about to be sent.
    //
    // Driven by a token app.py renders rather than by "the conversation looks empty":
    // the token says a clear HAPPENED, which is different from the transcript being
    // empty, and only the first tells us the box should be emptied. Compared against
    // the last token acted on, so a reader who starts typing straight after clearing
    // does not have it taken away again on the next mutation frame.
    function resetComposerOnClear() {
        var marker = doc.getElementById('composer-reset');
        if (!marker) return;
        var token = marker.getAttribute('data-token') || '';
        if (view.__sageClearToken === undefined) {
            // First sight of the page: adopt the token without clearing, or a reload
            // would wipe a question the reader had already typed.
            view.__sageClearToken = token;
            return;
        }
        if (view.__sageClearToken === token) return;
        view.__sageClearToken = token;
        var box = doc.querySelector('.stChatInput textarea');
        if (box && box.value) {
            setFieldValue(box, '');
            box.style.height = 'auto';
        }
        view.__sageHistoryAt = -1;
        view.__sageHistoryDraft = '';
        // And anything queued, which belongs to the conversation being left. This
        // token moves on a clear, on New chat and on opening another chat — see
        // `state._leave_conversation` — so it is exactly the signal for "the questions
        // waiting behind that answer are not wanted any more". Without it, clearing the
        // page and then watching a question you had queued arrive in the empty
        // conversation a second later is the app answering something nobody asked.
        view.__sageQueue = [];
        view.__sageSending = null;
        view.__sageSendTries = 0;
        view.__sageDraftHold = null;
    }

    // Close the model picker once a model has been picked.
    //
    // Streamlit leaves the popover open across the rerun, so the panel stayed up over
    // the conversation and had to be dismissed by clicking somewhere else — after
    // choosing, which is the one moment there is nothing left to choose. Base Web
    // closes its popover on Escape, so that is what this sends.
    //
    // Delegated from the document, because the panel is rendered in a portal that
    // Streamlit rebuilds on every rerun: a listener bound to the panel itself would
    // be attached to a node that no longer exists by the time it is needed.
    //
    // Two selectors, because Streamlit moved the panel. Up to 1.58 it was a Base Web
    // popover; 1.59 removed Base Web and renders the body into a floating-ui portal
    // on `document.body` instead. This shipped matching only `[data-baseweb=popover]`,
    // which on a current Streamlit matches nothing at all — so the Escape was never
    // sent and the picker went on staying open, the exact bug it was added to fix.
    // requirements.txt allows >=1.42, so both shapes are live and both are named.
    var PANEL = '[data-testid="stPopoverBody"], [data-baseweb="popover"]';

    function closePickerOnPick() {
        if (view.__sagePickerOff) {
            try { view.__sagePickerOff(); } catch (err) { /* realm gone */ }
        }
        var onClick = function (event) {
            var button = event.target && event.target.closest
                ? event.target.closest('button')
                : null;
            // Scoped to the model list, not to "any button in any popover". The wider
            // rule was harmless only because the picker is currently the one popover
            // in the app with buttons in it; a date picker or a multiselect added later
            // would have inherited an Escape nobody asked for.
            if (!button || !button.closest('.st-key-model-list')) return;
            if (!button.closest(PANEL)) return;
            // After the click has been delivered, not instead of it.
            view.setTimeout(function () {
                // Both events, with the same init. Base Web's popover has bound its
                // dismissal to `keyup` in some versions and `keydown` in others, and
                // which one is installed is not visible from this repo — sending one
                // and hoping is how a feature becomes a silent no-op.
                ['keydown', 'keyup'].forEach(function (kind) {
                    doc.dispatchEvent(new view.KeyboardEvent(kind, {
                        key: 'Escape', code: 'Escape', keyCode: 27, which: 27,
                        bubbles: true, cancelable: true
                    }));
                });
            }, 0);
        };
        doc.addEventListener('click', onClick, true);
        view.__sagePickerOff = function () {
            doc.removeEventListener('click', onClick, true);
        };
    }

    function copyText(text) {
        // The PARENT's clipboard. This iframe is never focused — the click that gets
        // here happened in the page around it — so Chromium rejects the iframe's own
        // `writeText` with NotAllowedError, which the caller's empty `.catch` then
        // swallowed: a copy button that looked fine and copied nothing.
        var nav = view.navigator || navigator;
        if (nav.clipboard && nav.clipboard.writeText) {
            return nav.clipboard.writeText(text);
        }
        // Fallback for insecure (http) origins without the async clipboard API.
        return new Promise(function (resolve, reject) {
            try {
                var area = doc.createElement('textarea');
                area.value = text;
                area.style.position = 'fixed';
                area.style.opacity = '0';
                doc.body.appendChild(area);
                area.focus();
                area.select();
                var ok = doc.execCommand('copy');
                doc.body.removeChild(area);
                if (ok) { resolve(); } else { reject(); }
            } catch (err) { reject(err); }
        });
    }

    function makeCopyButton(getText, label, className) {
        var btn = injected('button');
        btn.type = 'button';
        btn.className = className || 'rcc-copy-btn';
        btn.innerHTML = COPY_SVG;
        btn.title = label;
        btn.setAttribute('aria-label', label);
        btn.addEventListener('click', function (event) {
            event.preventDefault();
            event.stopPropagation();
            copyText(getText()).then(function () {
                btn.innerHTML = CHECK_SVG;
                btn.dataset.copied = 'true';
                btn.setAttribute('aria-label', 'Copied');
                setTimeout(function () {
                    btn.innerHTML = COPY_SVG;
                    delete btn.dataset.copied;
                    btn.setAttribute('aria-label', label);
                }, 2000);
            }).catch(function () {});
        });
        return btn;
    }

    function addCodeCopyButtons() {
        var blocks = doc.querySelectorAll('.stChatMessage div[data-testid="stCodeBlock"]');
        blocks.forEach(function (block) {
            if (block.dataset.sageCopy === 'true') return;
            var pre = block.querySelector('pre');
            var code = block.querySelector('code');
            if (!pre || !code) return;
            block.dataset.sageCopy = 'true';
            pre.style.setProperty('position', 'relative', 'important');
            pre.appendChild(makeCopyButton(function () {
                return code.innerText || code.textContent || '';
            }, 'Copy code to clipboard'));
        });
    }

    // What "copy this answer" would put on the clipboard. The `Stopped` marker is not
    // part of the answer — it is this app saying what happened to it — so it does not
    // travel with the text, and a turn whose only content is that marker has nothing
    // to copy at all.
    function answerText(message) {
        var body = message.querySelector('[data-testid="stChatMessageContent"]')
            || message;
        var copy = body.cloneNode(true);
        copy.querySelectorAll('.stopped-note').forEach(function (note) {
            note.remove();
        });
        return (copy.innerText || copy.textContent || '').trim();
    }

    function addAnswerCopyButtons() {
        // Keyed answer containers only, so the streaming status row never gets one.
        var answers = doc.querySelectorAll('[class*="st-key-answer-"] .stChatMessage');
        answers.forEach(function (message) {
            if (message.dataset.sageCopy === 'true') return;
            // A turn stopped before its first token is a real message — it has to be
            // on the page, or the reader is left with their question and nothing under
            // it — but it holds no answer. A copy button on it offers to put the empty
            // string on the clipboard, which is a control that can only disappoint.
            if (!answerText(message)) return;
            message.dataset.sageCopy = 'true';
            // Anchored to the keyed container, not to the message, because app.css
            // reserves the gutter there — on the message alone the prose and the code
            // blocks shrank while the Sources strip beside them did not, leaving the
            // answer with three different right edges. The button still lands in the
            // same corner: the container's top edge IS the message's.
            var host = message.closest('[class*="st-key-answer-"]') || message;
            host.style.setProperty('position', 'relative');
            var btn = makeCopyButton(function () {
                return answerText(message);
            }, 'Copy this answer');
            btn.style.top = '0';
            btn.style.right = '0';
            btn.style.opacity = '0.65';
            host.appendChild(btn);
        });
    }

    /* --- asking about a passage of an answer -------------------------------
     *
     * Select a sentence in an answer and a button appears under it; pressing it puts
     * a draft in the composer quoting what was selected, with the cursor after it.
     *
     * A DRAFT, never a question. The reader chose a passage, not a thing to ask about
     * it, and sending "About this part of your answer: …" on its own gets a reply
     * asking what they wanted to know. So this fills the box and focuses it, which is
     * the one thing a reader cannot do for themselves without retyping the passage.
     *
     * Ported from the same control on the owner's site (`assets/js/chat.js` in
     * personal-website), including the two things that are not obvious there: the
     * selection has to be kept alive through the click, which means cancelling
     * `mousedown` rather than `click`; and the draft that was just used has to be
     * suppressed until the selection changes, because focusing the composer moves the
     * selection and fires `selectionchange`, which brought the bubble straight back
     * over the passage it had just handed over.
     */

    // Below this it is a stray click, above it a select-all rather than a passage.
    var ASK_MIN = 12, ASK_MAX = 1200;
    // What goes in the composer. Long enough for a paragraph, short enough that the
    // reader can still see their own question after it.
    var ASK_QUOTE = 600;

    function askBubble() {
        var bubble = doc.getElementById('ask-selection');
        if (bubble) return bubble;
        bubble = injected('button');
        bubble.id = 'ask-selection';
        bubble.type = 'button';
        bubble.hidden = true;
        bubble.textContent = 'Ask about this';
        // The selection dies on mousedown anywhere else, and reading it is the whole
        // job — so this one is cancelled and the work happens on click.
        bubble.addEventListener('mousedown', function (event) {
            event.preventDefault();
        });
        bubble.addEventListener('click', function () {
            var draft = bubble.dataset.draft || '';
            bubble.hidden = true;
            if (!draft) return;
            var box = doc.querySelector('.stChatInput textarea');
            if (!box) return;
            // Appended, not assigned: a reader who had already typed half a follow-up
            // before selecting the line it is about should not lose it.
            var existing = box.value ? box.value.replace(/\s*$/, '') + '\n\n' : '';
            setFieldValue(box, existing + draft);
            box.focus();
            try {
                box.selectionStart = box.selectionEnd = box.value.length;
            } catch (err) { /* not all browsers allow it on a focused textarea */ }
            // After the focus, which moves the selection and fires selectionchange.
            consumedAsk = draft;
        });
        doc.body.appendChild(bubble);
        return bubble;
    }

    var consumedAsk = '';

    // Grow a part-selected sentence out to its edges, so a drag that stopped mid-word
    // still quotes something readable.
    function sentenceBounds(raw, from, to) {
        var start = 0, end = raw.length;
        var before = raw.slice(0, from).lastIndexOf('. ');
        if (before !== -1) start = before + 2;
        var after = raw.slice(to).search(/[.!?](\s|$)/);
        if (after !== -1) end = to + after + 1;
        return [start, end];
    }

    function clipQuote(text) {
        if (text.length <= ASK_QUOTE) return text;
        var cut = text.slice(0, ASK_QUOTE);
        var space = cut.lastIndexOf(' ');
        if (space > ASK_QUOTE * 0.6) cut = cut.slice(0, space);
        return cut.replace(/[\s,;:.]+$/, '') + '…';
    }

    // The selection, if it is inside an answer and is a passage rather than a stray.
    //
    // Answers only. A question is the reader's own words — they do not need a quoting
    // control to ask about something they typed — and the status row is not text at
    // all. `[class*="st-key-answer-"]` is the same hook the copy button uses, which
    // means a streaming answer has no container yet and is left alone: quoting half a
    // sentence that is still being written is not a passage.
    function selectionInAnswer() {
        var selection = view.getSelection && view.getSelection();
        if (!selection || selection.isCollapsed || !selection.rangeCount) return null;
        var text = selection.toString().replace(/\s+/g, ' ').trim();
        if (text.length < ASK_MIN || text.length > ASK_MAX) return null;
        var range = selection.getRangeAt(0);
        var node = range.commonAncestorContainer;
        var element = node.nodeType === 1 ? node : node.parentNode;
        if (!element || !element.closest) return null;
        if (!element.closest('[class*="st-key-answer-"] .stChatMessage')) return null;

        // Widened against the block the selection STARTS in. A drag across two
        // paragraphs has the answer itself as its common ancestor, and the answer's
        // textContent is every paragraph run together.
        var from = range.startContainer;
        var edge = from.nodeType === 1 ? from : from.parentNode;
        var block = edge && edge.closest
            ? edge.closest('p, li, blockquote, td, th, h1, h2, h3, h4, h5, h6')
            : null;
        var quote = text;
        if (block) {
            var raw = (block.textContent || '').replace(/\s+/g, ' ').trim();
            var at = raw.indexOf(text);
            if (at !== -1) {
                var bounds = sentenceBounds(raw, at, at + text.length);
                var grown = raw.slice(bounds[0], bounds[1]).trim();
                if (grown.length > quote.length && grown.length <= ASK_MAX) {
                    quote = grown;
                }
            }
        }
        return {text: clipQuote(quote), rect: range.getBoundingClientRect()};
    }

    function draftFor(found) {
        return found ? 'About this part of your answer: "' + found.text + '" — ' : '';
    }

    function placeAskBubble() {
        var bubble = askBubble();
        var found = selectionInAnswer();
        // Never over a turn in flight: the composer is blocked while one runs, so a
        // draft would land in a box that cannot be sent.
        if (!found || isProcessing()) {
            bubble.hidden = true;
            return;
        }
        var draft = draftFor(found);
        if (draft === consumedAsk) {
            bubble.hidden = true;
            return;
        }
        bubble.dataset.draft = draft;
        bubble.hidden = false;
        // Fixed, in viewport coordinates, so it does not need to know which of this
        // page's four candidate scroll containers is the one that moves — a question
        // the rest of this file spends sixty lines on. It hides on any scroll instead.
        var width = bubble.offsetWidth || 120;
        var left = found.rect.left + found.rect.width / 2 - width / 2;
        bubble.style.top = Math.min(
            found.rect.bottom + 8, view.innerHeight - 48
        ) + 'px';
        bubble.style.left = Math.max(
            8, Math.min(left, view.innerWidth - width - 8)
        ) + 'px';
    }

    // Registered once per COPY of this script, and the distinction is the whole
    // comment.
    //
    // Streamlit rebuilds the component iframe on every rerun, so these listeners die
    // with their realm — while anything parked on the parent window survives. Guard on
    // a parent-side flag and the next copy sees "already wired" when no listener
    // exists anywhere, which is how this shipped broken the first time and is the
    // failure `addPasteHandler` above documents. Tear down and re-register on every
    // pass instead and the opposite happens: `sync()` runs on every DOM mutation, and
    // positioning the bubble IS a mutation, so the pass triggered by showing the
    // bubble removed it again —
    // `placeAskBubble` ran, no bubble ever survived to be clicked.
    //
    // So both halves are needed and they are different halves. `askWired` is a plain
    // closure variable: it dies with this realm, so a fresh copy registers exactly
    // once and this copy never re-registers. `view.__sageAskOff` is the handle that
    // outlives the realm, so the fresh copy can unhook the dead copy's listeners.
    // The bubble is cleared at the same moment, because its click handler is a
    // closure in the dead realm and a bubble that cannot answer a click is worse than
    // no bubble.
    var askWired = false;

    function addSelectionAsk() {
        if (askWired) return;
        askWired = true;
        if (view.__sageAskOff) {
            try { view.__sageAskOff(); } catch (err) { /* realm already gone */ }
        }
        var stale = doc.getElementById('ask-selection');
        if (stale) stale.remove();

        // On mouseup rather than on selectionchange: showing it mid-drag makes the
        // button chase the cursor across the answer.
        var onUp = function () { view.setTimeout(placeAskBubble, 10); };
        var onKey = function (event) {
            if (event.shiftKey || event.key === 'Shift') {
                view.setTimeout(placeAskBubble, 10);
            }
        };
        var onChange = function () {
            var found = selectionInAnswer();
            if (!found || draftFor(found) !== consumedAsk) consumedAsk = '';
            var bubble = doc.getElementById('ask-selection');
            // Only ever hides here, for the reason above.
            if (bubble && !bubble.hidden && !found) bubble.hidden = true;
        };
        var onScroll = function () {
            var bubble = doc.getElementById('ask-selection');
            if (bubble && !bubble.hidden) bubble.hidden = true;
        };
        doc.addEventListener('mouseup', onUp);
        doc.addEventListener('keyup', onKey);
        doc.addEventListener('selectionchange', onChange);
        doc.addEventListener('scroll', onScroll, true);

        view.__sageAskOff = function () {
            doc.removeEventListener('mouseup', onUp);
            doc.removeEventListener('keyup', onKey);
            doc.removeEventListener('selectionchange', onChange);
            doc.removeEventListener('scroll', onScroll, true);
        };
    }

    /* --- the send button, while an answer is generating -------------------- */

    // Both halves of the swap live here: the arrow goes and the square arrives, in one
    // pass, so there is no frame with two buttons in one corner or none in it.
    //
    // This used to build a <style> element and inject it into the parent's <head> to
    // grey the arrow out. The rule is in app.css now, keyed off the attribute set
    // below — a stylesheet is where the reader of this app looks to find out what the
    // composer is painted with, and `tools/palette_check.py` reads that file and not
    // this one, so a rule hidden here was a rule outside the guard.
    //
    // The square is a button this script owns rather than the arrow re-dressed.
    // Streamlit's button belongs to React, which rebuilds it whenever it likes and
    // would take any innerHTML written into it back out again — and a click handler
    // added to it would still be the *send* handler underneath.
    function markGenerating() {
        var container = doc.querySelector('[data-testid="stChatInput"]');
        var busy = isProcessing();

        if (busy) doc.body.dataset.sageGenerating = 'true';
        else delete doc.body.dataset.sageGenerating;

        if (container) {
            var send = container.querySelector('button:not(#paperclip-btn):not(#stop-btn)');
            if (send) {
                if (busy) send.setAttribute('aria-disabled', 'true');
                else send.removeAttribute('aria-disabled');
            }
            var stop = doc.getElementById('stop-btn');
            if (busy && !stop) {
                stop = injected('button');
                stop.id = 'stop-btn';
                stop.type = 'button';
                stop.innerHTML = STOP_SVG;
                stop.title = 'Stop generating';
                stop.setAttribute('aria-label', 'Stop generating');
                stop.addEventListener('click', function (event) {
                    event.preventDefault();
                    event.stopPropagation();
                    // The widget app.py clips to a pixel. Clicking it is what tells
                    // Python a stop was asked for; the click is also what aborts the
                    // run that is streaming, which is the same event doing both jobs.
                    var hook = widgetButton('.st-key-stop-generation');
                    if (hook) hook.click();
                });
                container.appendChild(stop);
            } else if (!busy && stop) {
                stop.remove();
            }
        }

        // Re-registered on every run, not once per textarea. A listener added here is a
        // closure belonging to this copy of the script, and Streamlit rebuilds the
        // iframe it is served in on every rerun — after which the closure's realm is
        // gone and the listener never fires again. That is not a theory: the theme
        // toggle was built the "add it once" way and was dead from the first click,
        // measured. It only escaped notice here because Streamlit usually rebuilds the
        // chat input's DOM too, so the marker went with it and a fresh listener was
        // added by luck. `__sageEnterOff` makes it deliberate — the same shape
        // `addPromptHistory` and the drag, paste and selection handlers already use.
        var area = doc.querySelector('textarea[data-testid="stChatInputTextArea"]');
        if (area) {
            if (view.__sageEnterOff) {
                try { view.__sageEnterOff(); } catch (err) { /* node gone */ }
            }
            var onEnter = function (event) {
                if (event.key !== 'Enter' || event.shiftKey) return;
                // The Enter that confirms an IME candidate belongs to the IME, and
                // this used to swallow it: a reader composing Chinese, Japanese or
                // Korean could not accept a candidate at all while an answer was
                // arriving. It is not a send, so nothing below has to happen either.
                if (event.isComposing) return;
                if (!isProcessing()) return;
                event.preventDefault();
                event.stopImmediatePropagation();
                queueDraft(area);
            };
            area.addEventListener('keydown', onEnter, true);
            view.__sageEnterOff = function () {
                area.removeEventListener('keydown', onEnter, true);
            };
        }
    }

    /* --- a question asked while the last one is still being answered ----- */
    //
    // Pressing Enter mid-answer used to do nothing at all: the handler above blocked
    // it, and the send button is the stop square for the duration, so a reader who had
    // already thought of the next question had to hold it, watch the answer land, and
    // then type it again. What it does now is take the question and hold it, and send
    // it the moment the turn ends.
    //
    // Held HERE and not in session state, which is not a shortcut: reaching Python
    // means a widget interaction, and a widget interaction during a run aborts that
    // run — it is the mechanism the stop button is built on. A queue that told the
    // server about itself would end the answer it is queued behind. So Python never
    // learns of these until one is actually sent, at which point it is an ordinary
    // question typed into an ordinary box.
    //
    // On the parent window, because Streamlit rebuilds this script's iframe on every
    // rerun and the whole point is to survive the rerun at the end of a turn.

    function queue() {
        if (!view.__sageQueue) view.__sageQueue = [];
        return view.__sageQueue;
    }

    function queueDraft(area) {
        var text = (area.value || '').replace(/^\s+|\s+$/g, '');
        if (!text) return;
        queue().push(text);
        // Emptied, so the box is ready for the question after it and the reader can
        // see that the one they pressed Enter on has been taken.
        setFieldValue(area, '');
        area.style.height = 'auto';
        // The same reset a real send does — the next Up starts from the newest
        // question rather than from wherever the last walk stopped.
        view.__sageHistoryAt = -1;
        view.__sageHistoryDraft = '';
        schedule();
    }

    // Take one back. Identified by its text as well as by its position, because the
    // ✕ belongs to the row that was drawn and the queue can move underneath it: the
    // frame after `flushQueue` shifts the first question off, the rows on screen are
    // one behind, and a click landing in that window would drop the question next to
    // the one the reader pointed at.
    function dropQueued(index, text) {
        var held = queue();
        var at = held[index] === text ? index : held.indexOf(text);
        if (at < 0) return;
        held.splice(at, 1);
        schedule();
    }

    // Drawn where the question will actually appear — the end of the conversation, in
    // the corner a question sits in — rather than as a chip by the composer. A reader
    // who has queued something is looking at the answer above it, and the thing they
    // need to see is that their question is next in line.
    //
    // Rebuilt only when the queue's contents change: this runs on every mutation frame,
    // and re-creating the row every time would drop the ✕ out from under the cursor.
    function renderQueue() {
        var held = queue();
        var note = doc.getElementById('queued-prompts');
        if (!held.length) {
            if (note) note.remove();
            return;
        }
        var host = doc.querySelector('[data-testid="stMainBlockContainer"]');
        if (!host) return;
        if (!note) {
            note = injected('div');
            note.id = 'queued-prompts';
            note.className = 'queued-note';
        }
        // Last child, always: Streamlit appends the streaming answer as it goes, so a
        // node merely present in the container drifts up above content that arrived
        // after it.
        if (note.parentElement !== host || note.nextSibling) host.appendChild(note);

        var stamp = held.length + '\u0000' + held.join('\u0000');
        if (note.dataset.sageQueue === stamp) return;
        note.dataset.sageQueue = stamp;
        note.textContent = '';
        held.forEach(function (text, index) {
            var row = doc.createElement('div');
            row.className = 'queued-row';

            var drop = doc.createElement('button');
            drop.type = 'button';
            drop.className = 'queued-drop';
            drop.innerHTML = CLOSE_SVG;
            drop.title = 'Do not send this question';
            drop.setAttribute('aria-label', drop.title);
            drop.addEventListener('click', function (event) {
                event.preventDefault();
                event.stopPropagation();
                dropQueued(index, text);
            });

            var bubble = doc.createElement('div');
            bubble.className = 'queued-bubble';
            var label = doc.createElement('span');
            label.className = 'queued-label';
            label.textContent = held.length > 1
                ? 'Queued · ' + (index + 1) + ' of ' + held.length
                : 'Queued';
            bubble.appendChild(label);
            // textContent, not innerHTML: this is the reader's own typing and it goes
            // on the page as text.
            bubble.appendChild(doc.createTextNode(text));

            row.appendChild(drop);
            row.appendChild(bubble);
            note.appendChild(row);
        });
    }

    function sendButton() {
        var container = doc.querySelector('[data-testid="stChatInput"]');
        if (!container) return null;
        return container.querySelector(
            'button:not(#paperclip-btn):not(#stop-btn):not([' + INJECTED + '])'
        );
    }

    // Put back whatever the reader was typing when a queued question took the box off
    // them. Only into an empty box — if they have started typing again since, that is
    // newer than what is being restored.
    function restoreDraft() {
        var draft = view.__sageDraftHold;
        view.__sageDraftHold = null;
        if (!draft) return;
        var area = doc.querySelector('textarea[data-testid="stChatInputTextArea"]');
        if (!area || area.value) return;
        setFieldValue(area, draft);
    }

    // How many questions Python has accepted. This is the receipt a send is confirmed
    // by, and getting it wrong cost a question: the first version read the box instead,
    // on the reasoning that Streamlit empties the field on submit — so an empty box
    // meant "sent". It does not. The box is also empty in the window between the click
    // and Streamlit running the script, and in that window the next queued question
    // was written into the same widget and submitted over the top of the one already
    // in flight. Two questions went to the box, one turn came back: measured in the
    // running app, "second question" never reached the transcript at all.
    //
    // A bubble in the transcript, by contrast, exists only because a script run
    // appended a message — so it cannot be true early. Counted rather than matched on
    // text: `transcript.escape` turns a newline into `<br>`, which leaves no whitespace
    // in `textContent` at all, so a pasted multi-line question would never match itself
    // and would be handed back as unsendable.
    function questionCount() {
        return doc.querySelectorAll('.user-bubble').length;
    }

    // One queued question per turn, sent by driving the composer the reader would have
    // driven: the text into the box, then Streamlit's own send button. Nothing else
    // here can start a turn — `st.chat_input` is the only widget that carries a
    // question to Python — and going through it means a queued question is subject to
    // every check a typed one is, the length limit and the rate limiter included.
    //
    // A click that does not land is retried, because it can be made in the frame where
    // React still has the send button disabled. Retried on a clock and not on the sync
    // pass, though: passes run several times a second while an answer streams, and a
    // retry faster than the server's round trip is how a double submit happens. After
    // a few seconds of no receipt it gives up and PUTS THE TEXT BACK IN THE BOX — a
    // question the reader can see and send themselves, rather than one that vanished.
    // A turn the limiter refuses ends up here, which is the right place for it: the
    // refusal is on screen and the question is in the box next to it.
    var SEND_RETRY_MS = 500;
    var SEND_GIVE_UP = 12;
    // How long to wait for a turn that was accepted but never appeared. A question the
    // rate limiter refuses appends no message, so the receipt below would never arrive
    // and the rest of the queue would sit behind it for ever.
    //
    // Six seconds, not the ten it started at, because this is time the reader spends
    // looking at an empty box wondering where their question went. A drain that is
    // going to work puts a bubble on the page within a rerun — measured at one to two
    // seconds against a local provider — so the only cost of being impatient is a
    // question typed back into the box a moment before the turn it belongs to starts,
    // which `restoreDraft` will not overwrite and the reader can simply delete.
    var SEND_PATIENCE_MS = 6000;

    function flushQueue() {
        var area = doc.querySelector('textarea[data-testid="stChatInputTextArea"]');
        if (!area) return;
        var sending = view.__sageSending;

        if (sending !== null && sending !== undefined) {
            // The receipt: Python has appended a question to the transcript.
            if (questionCount() > (view.__sageSendSeen || 0)) {
                view.__sageSending = null;
                view.__sageSendTries = 0;
                restoreDraft();
                return;
            }
            // Two very different states look alike here, and telling them apart is the
            // whole of this branch. Streamlit empties its chat input when it ACCEPTS a
            // submit, so a box that no longer holds the text means the question is on
            // its way and the only thing to do is wait for the receipt above. A box
            // that still holds it means the click was made in a frame where React had
            // the send button disabled, and nothing has been submitted at all.
            //
            // Conflating the two double-asked a question. The first version retried on
            // a 400ms clock without checking the box, and `handToComposer` re-fills the
            // box before clicking — so a server round trip slower than 400ms (which is
            // what a panel full of chat rows made it) was read as a lost click, the
            // text was typed back in, and the same question was submitted twice.
            // Measured: "third question" answered twice, four answers for three
            // questions.
            if (area.value !== sending) {
                if (Date.now() - (view.__sageSentAt || 0) > SEND_PATIENCE_MS) {
                    // Submitted, and no question ever appeared. The turn was refused
                    // rather than lost: `may_start_turn` puts the reason in the notice
                    // strip and appends no message, which is exactly this shape. So the
                    // question goes back into the box, next to the sentence explaining
                    // why it did not go — measured on a session that ran past
                    // `RATE_BURST`, where a queued question had until now vanished
                    // without a word.
                    view.__sageSending = null;
                    view.__sageSendTries = 0;
                    view.__sageDraftHold = null;
                    if (!area.value) setFieldValue(area, sending);
                }
                return;
            }
            if (isProcessing()) return;
            if (Date.now() - (view.__sageSentAt || 0) < SEND_RETRY_MS) return;
            var tries = (view.__sageSendTries || 0) + 1;
            view.__sageSendTries = tries;
            if (tries > SEND_GIVE_UP) {
                // Give up and leave the text where the reader can see it and send it
                // themselves, rather than losing the question.
                view.__sageSending = null;
                view.__sageSendTries = 0;
                view.__sageDraftHold = null;
                return;
            }
            handToComposer(area, sending);
            return;
        }

        var held = queue();
        if (!held.length || isProcessing()) return;
        // Never over the top of a question being typed: it is held and put back once
        // the queued one has gone.
        var draft = (area.value || '');
        view.__sageDraftHold = draft.replace(/^\s+|\s+$/g, '') ? draft : null;
        view.__sageSending = held.shift();
        view.__sageSendTries = 0;
        view.__sageSendSeen = questionCount();
        handToComposer(area, view.__sageSending);
    }

    function handToComposer(area, text) {
        view.__sageSentAt = Date.now();
        if (area.value !== text) {
            setFieldValue(area, text);
            area.style.height = 'auto';
        }
        var send = sendButton();
        if (send) send.click();
    }

    /* --- reopening a question -------------------------------------------- */

    // A pencil in the gutter beside each question, wired to the clipped Streamlit
    // button app.py renders directly after that question.
    //
    // Paired by ordinal rather than by walking the DOM from the bubble outwards. The
    // walk would have to name `[data-testid="stElementContainer"]` to find the
    // sibling, and that is an unversioned Streamlit test id — the one kind of rule
    // this repo has written down not to write, because it fails silently the day it
    // changes. Two lists read in document order cannot: app.py renders exactly one
    // hook per question, immediately after it, so the Nth of each belong together.
    // If the two lists ever disagree, nothing is injected at all rather than every
    // pencil editing the wrong question.
    function editHooks() {
        return doc.querySelectorAll('[class*="st-key-edit-open-"]');
    }

    // The question's own text, without the attachment chips that live inside its
    // bubble. `textContent` runs them together with the words — a turn with a file on
    // it reads as "🖼️ pasted-image-1.pngHow do I read this log?" — so they come off a
    // clone first, the same way `askedBefore()` does it for the prompt history.
    function questionText(row) {
        var bubble = row.querySelector('.user-bubble') || row;
        var copy = bubble.cloneNode(true);
        copy.querySelectorAll('.attachment-badges, .attachment-badge')
            .forEach(function (badge) { badge.remove(); });
        return (copy.innerText || copy.textContent || '').trim();
    }

    // A copy button beside every question, including the one being answered right
    // now: copying costs no turn and reruns nothing, so unlike the pencil there is no
    // reason to take it away mid-answer. Injected separately from the pencil for that
    // reason, and because it needs no Streamlit widget behind it — the clipboard is
    // something this script can reach on its own.
    function addQuestionCopyButtons() {
        doc.querySelectorAll('.user-message').forEach(function (row) {
            if (row.querySelector('.user-copy-btn')) return;
            var btn = makeCopyButton(function () {
                return questionText(row);
            }, 'Copy this question', 'user-copy-btn');
            // After the pencil in the DOM but before the bubble, so the row reads
            // copy, edit, question from the left.
            row.insertBefore(btn, row.firstChild);
        });
    }

    function addEditButtons() {
        var bubbles = doc.querySelectorAll('.user-message');
        var hooks = editHooks();
        // One question may legitimately have no hook, and only one: the one being
        // answered right now, which app.py draws from the turn block without one
        // because a question cannot be rewritten while its answer is arriving. Any
        // other disagreement means these two lists are not what this function thinks
        // they are, and pairing them anyway would put a pencil that edits question 2
        // beside question 3. Nothing is injected in that case.
        if (!hooks.length) return;
        if (bubbles.length < hooks.length || bubbles.length - hooks.length > 1) return;

        for (var index = 0; index < hooks.length; index++) {
            var row = bubbles[index];
            var hook = hooks[index].querySelector(NOT_INJECTED);
            if (!row || !hook) continue;
            var btn = row.querySelector('.user-edit-btn');
            if (!btn) {
                btn = injected('button');
                btn.type = 'button';
                btn.className = 'user-edit-btn';
                btn.innerHTML = PENCIL_SVG;
                btn.title = 'Edit this question and ask it again';
                btn.setAttribute('aria-label', btn.title);
                btn.addEventListener('click', onEditClick);
                // Before the bubble, so the flex row puts it in the empty space to
                // the left of it rather than past the right-hand edge of the page.
                row.insertBefore(btn, row.firstChild);
            }
            // The POSITION, not the node. Streamlit rebuilds a rerun's widgets while
            // leaving the markdown block this pencil lives in alone, so a handler
            // holding the hook it was created with ends up holding a detached button
            // and `click()` on that does nothing at all: the pencil opened the editor
            // once per page load and was silently inert for the rest of the session.
            // Re-read at click time instead, which cannot go stale.
            btn.dataset.sageEditIndex = index;
            // Refreshed every pass, not set once: app.py disables these hooks while
            // an answer generates — a click would be a rerun, which abandons the
            // answer on screen — and app.css hides a disabled pencil. Without this
            // the reader is offered a control that silently does nothing for as long
            // as the turn runs.
            btn.disabled = hook.disabled;
        }
    }

    function onEditClick(event) {
        event.preventDefault();
        event.stopPropagation();
        var index = parseInt(this.dataset.sageEditIndex, 10);
        var hooks = editHooks();
        var hook = hooks[index] && hooks[index].querySelector(NOT_INJECTED);
        if (hook) hook.click();
    }

    /* --- type to focus --------------------------------------------------- */

    // One listener, replaced each run rather than added each run. Registered without a
    // teardown it piled up one per rerun — hundreds over a long session, all but the
    // newest belonging to a destroyed realm and doing nothing.
    if (view.__sageTypeOff) {
        try { view.__sageTypeOff(); } catch (err) { /* previous realm */ }
    }
    var onType = function (event) {
        if (event.ctrlKey || event.altKey || event.metaKey) return;
        // A single printable character only: never swallow Tab, Escape, arrows,
        // function keys, or Space/Enter aimed at a control.
        if (!event.key || event.key.length !== 1) return;
        var target = event.target;
        if (!target) return;
        if (target.isContentEditable) return;
        var tag = target.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
        if (target.closest && target.closest('button, a, [role="button"], [role="dialog"]')) return;

        var input = doc.querySelector('textarea[data-testid="stChatInputTextArea"]');
        if (input) input.focus();
    };
    doc.addEventListener('keydown', onType);
    view.__sageTypeOff = function () {
        doc.removeEventListener('keydown', onType);
    };

    /* --- scheduling ------------------------------------------------------ */

    function sync() {
        // Measurement FIRST. It used to run after the injectors, all of them inside
        // one try/catch, so a single throw anywhere above cost the whole pass its
        // layout: `--bar-h` went unpublished and the frame rendered on the
        // stylesheet's fallback. `addPaperclip` could not even recover, because it
        // guards on the element it had failed to create, so it threw at the same
        // place forever and the bar was never measured again.
        //
        // Order among the three below still matters: the bar's height is what the
        // page reserves for it, the slack above a short conversation is measured
        // against that reservation, and autoScroll measures the gap they leave.
        measureChrome();
        addPaperclip();
        addPasteHandler();
        addDropHandler();
        addPromptHistory();
        resetComposerOnClear();
        closePickerOnPick();
        addCodeCopyButtons();
        addAnswerCopyButtons();
        addEditButtons();
        addQuestionCopyButtons();
        addSelectionAsk();
        addThemeToggle();
        labelPanelToggles();
        labelChatActions();
        enforceTheme();
        markGenerating();
        // After `markGenerating`, which is what decides whether a turn is in flight,
        // and before the scroll below, which measures a page this may have just added
        // a row to.
        renderQueue();
        flushQueue();
        // `scroller()` first, because it is the one that asks which element actually
        // scrolls instead of assuming. This line named stMain outright while
        // `autoScroll()` two lines down asked `scroller()` — two functions in one file
        // disagreeing about which element is the scrollport. On a page where the
        // document scrolls and stMain does not, stMain reports
        // scrollHeight == clientHeight however long the conversation is, so `fill()`
        // read the page as short and padded slack above one that already scrolled:
        // the reader's gap at the *top* of the page. The fallbacks are for when
        // nothing scrolls, which is exactly when `fill()` has work to do and needs a
        // viewport height to measure the slack against.
        var port = scroller() || doc.querySelector('[data-testid="stMain"]')
            || doc.scrollingElement;
        if (port) fill(port);
        autoScroll();
    }

    function safeSync() {
        try { sync(); } catch (err) { /* never break the page */ }
    }

    // Streaming mutates the DOM once per token. Running the full sync on every
    // mutation meant a document-wide querySelectorAll sweep per token; coalescing
    // keeps it O(frames) instead of O(tokens).
    //
    // A frame callback *and* a timer, whichever arrives first. Coalescing on rAF
    // alone assumes the page is painting: in a browser that is producing no
    // frames — headless Chrome under a virtual clock, a backgrounded tab — the
    // callback never ran, `queued` stayed true for ever, and every later mutation
    // was dropped on the floor. CI found that as a page still sized by the
    // stylesheet's fallbacks, several renders deep.
    var queued = false;
    function flush() {
        if (!queued) return;
        queued = false;
        safeSync();
    }

    function schedule() {
        if (queued) return;
        queued = true;
        window.requestAnimationFrame(flush);
        window.setTimeout(flush, 32);
    }

    // The theme first, and before the first sync: the attribute it sets is what
    // app.css picks a palette with, so a frame drawn without it is a frame of the
    // wrong colour on a page the reader is already looking at.
    try { applyTheme(themeChoice()); } catch (err) { /* the stylesheet still has both */ }

    // Straight away rather than a frame from now: until this has run, the page is
    // laid out around the stylesheet's guess at the input bar rather than its
    // measured height, and that is a frame the reader sees.
    safeSync();
    new MutationObserver(schedule).observe(doc.body, { childList: true, subtree: true });
    // Streaming appends text nodes that sometimes do not trigger the observer.
    //
    // And a queued question being handed to the composer needs the same poll, on a page
    // that is otherwise completely still. `flushQueue` waits on a clock — for a click
    // that did not land, or for a submit that was accepted and produced no turn — and
    // gated on `isProcessing()` alone those clocks never advanced: once the answer
    // finished and the page stopped mutating, nothing ran again. Measured with
    // `SAGE_RATE_BURST=1`, where the limiter refuses the queued question and appends
    // nothing: the reader was left with an empty box, a notice explaining the refusal,
    // and their question gone.
    setInterval(function () {
        if (isProcessing() || view.__sageSending !== null
                && view.__sageSending !== undefined) {
            schedule();
        }
    }, 250);

    // A resize changes what the page has to reserve for the input bar — the
    // disclaimer under it rewraps — and mutates nothing, so the observer above
    // never sees it. One listener on the page, retargeted to whichever copy of
    // this script is current: Streamlit rebuilds the iframe on every rerun, so
    // registering one per copy would pile up hundreds over a long session.
    view.__sageSync = schedule;
    if (!doc.body.dataset.sageResizeHook) {
        doc.body.dataset.sageResizeHook = 'true';
        view.addEventListener('resize', function () {
            if (view.__sageSync) view.__sageSync();
        });
    }
})();
