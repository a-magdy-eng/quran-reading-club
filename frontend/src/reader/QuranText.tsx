// Renders Quran pages as reflowable text.
//
// Pages are turned into a token stream: surah headings and basmalas are blocks,
// everything else flows inline. Inline tokens:
//   - page-start anchors (invisible; used to scroll to a page),
//   - verses with their number,
//   - margin markers for juz / hizb quarters (absolutely positioned into the
//     side gutter, vertically on the line where the quarter begins),
//   - page-end markers (a small ornament with the mushaf page number).
import { Fragment, type ReactNode } from "react";
import { arabicNumber } from "../format";
import type { QuranPage, Verse } from "../types";

type Inline =
  | { kind: "start"; page: number }
  | { kind: "verse"; v: Verse }
  | { kind: "mark"; quarter: number; juz: number | null }
  | { kind: "end"; page: number };

type Block =
  | { kind: "header"; sura: QuranPage["suras"][number]; basmala: string | null; startPage: number | null }
  | { kind: "para"; items: Inline[] };

const QUARTER_AR = ["", "ربع", "نصف", "ثلاثة أرباع"];
const QUARTER_EN = ["", "¼", "½", "¾"];

export function quarterLabel(q: number, juz: number | null): { ar: string; en: string } {
  const hizb = Math.ceil(q / 4);
  const part = (q - 1) % 4;
  if (juz) return { ar: `الجزء ${arabicNumber(juz)}`, en: `Juz ${juz} · Hizb ${hizb}` };
  return {
    ar: `${part ? QUARTER_AR[part] + " " : ""}الحزب ${arabicNumber(hizb)}`,
    en: `${part ? QUARTER_EN[part] + " " : ""}Hizb ${hizb}`,
  };
}

function buildBlocks(pages: QuranPage[], endMarkers: boolean): Block[] {
  const blocks: Block[] = [];
  let run: Inline[] = [];
  const flush = () => {
    if (run.length) blocks.push({ kind: "para", items: run });
    run = [];
  };
  for (const page of pages) {
    page.verses.forEach((v, i) => {
      if (v.sura_start) {
        flush();
        const sura = page.suras.find((s) => s.index === v.sura)!;
        blocks.push({ kind: "header", sura, basmala: v.basmala ? page.basmala_text : null, startPage: i === 0 ? page.page : null });
      } else if (i === 0) {
        run.push({ kind: "start", page: page.page });
      }
      if (v.quarter) run.push({ kind: "mark", quarter: v.quarter, juz: v.juz_start });
      run.push({ kind: "verse", v });
    });
    if (endMarkers) run.push({ kind: "end", page: page.page });
  }
  flush();
  return blocks;
}

function renderInline(t: Inline, key: string): ReactNode {
  switch (t.kind) {
    case "start":
      return <span key={key} className="page-anchor" data-start={t.page} />;
    case "mark": {
      const l = quarterLabel(t.quarter, t.juz);
      return (
        <span key={key} className={`side-mark ${t.juz ? "is-juz" : ""}`} title={l.en} aria-label={l.en}>
          <span className="side-mark-ar">{l.ar}</span>
          <span className="side-mark-en" dir="ltr">
            {l.en}
          </span>
        </span>
      );
    }
    case "end":
      return (
        <Fragment key={key}>
          {" "}
          <span className="page-end" data-end={t.page} title={`End of page ${t.page}`}>
            <span className="page-end-num">{arabicNumber(t.page)}</span>
          </span>{" "}
        </Fragment>
      );
    case "verse":
      return (
        <Fragment key={key}>
          <span className="aya" data-ref={`${t.v.sura}:${t.v.aya}`}>
            {t.v.text}
          </span>{" "}
          <span className="aya-num" aria-label={`Verse ${t.v.aya}`}>
            {arabicNumber(t.v.aya)}
          </span>{" "}
        </Fragment>
      );
  }
}

export function QuranText({ pages, endMarkers = true }: { pages: QuranPage[]; endMarkers?: boolean }) {
  const blocks = buildBlocks(pages, endMarkers);
  return (
    <>
      {blocks.map((b, i) =>
        b.kind === "header" ? (
          <div className="sura-block" key={`h${b.sura.index}-${i}`} data-start={b.startPage ?? undefined}>
            <div className="sura-header" dir="rtl">
              <span className="sura-side" dir="ltr">
                {b.sura.tname}
              </span>
              <span className="sura-name">سورة {b.sura.name}</span>
              <span className="sura-side" dir="ltr">
                {b.sura.ayas} āyāt · {b.sura.type === "Meccan" ? "Makki" : "Madani"}
              </span>
            </div>
            {b.basmala && <div className="basmala">{b.basmala}</div>}
          </div>
        ) : (
          <p className="ayat" key={`p${i}`}>
            {b.items.map((t, j) => renderInline(t, `${i}-${j}`))}
          </p>
        ),
      )}
    </>
  );
}
