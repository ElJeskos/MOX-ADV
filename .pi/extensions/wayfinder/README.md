# Lightweight Wayfinder picker for Pi

After adding or changing the extension, run `/reload` once.

Run `/wf` to:

1. load every open GitHub issue labelled `wayfinder:map`;
2. collect its open child issues;
3. show every open ticket with no open native blocker, regardless of assignee;
4. immediately continue with the selected ticket by sending:

```text
/wayfinder возьми в работу задачу <issue-url>
```

The picker performs no GitHub writes. Claiming and all later work remain the responsibility of the `wayfinder` workflow started by that prompt.

## Test

```sh
node --test .pi/extensions/wayfinder/model.test.ts
```
