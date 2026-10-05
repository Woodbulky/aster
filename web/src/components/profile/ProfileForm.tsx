"use client";

import type { ProfileDraft, ProfileKey } from "@/lib/api";
import { cn } from "@/lib/utils";

type Field = {
  key: ProfileKey;
  label: string;
  type?: "text" | "date" | "tel" | "number" | "select";
  options?: readonly string[];
  /** Shown instead of the stored option value. */
  labels?: Readonly<Record<string, string>>;
  placeholder?: string;
  hint?: string;
  /** Native constraints: the DB checks still have the final say. */
  attrs?: React.InputHTMLAttributes<HTMLInputElement>;
  wide?: boolean;
};

const YEAR = { min: 1990, max: 2035, step: 1 };
const PCT = { min: 0, max: 100, step: 0.01 };

export const SECTIONS = [
  {
    id: "about",
    title: "About you",
    blurb: "Your name exactly as it appears on your 10th marksheet.",
    fields: [
      { key: "full_name", label: "Full name", placeholder: "e.g. Aarav Sunil Patil", attrs: { autoComplete: "name", required: true } },
      { key: "full_name_local", label: "Name in Marathi / Hindi", placeholder: "उदा. आरव सुनील पाटील", hint: "Optional — some forms ask for it" },
      { key: "dob", label: "Date of birth", type: "date" },
      { key: "gender", label: "Gender", type: "select", options: ["Female", "Male", "Transgender"] },
      { key: "mobile", label: "Mobile number", type: "tel", placeholder: "10-digit number", attrs: { pattern: "[6-9][0-9]{9}", inputMode: "numeric", autoComplete: "tel-national" } },
      { key: "aadhaar_last4", label: "Aadhaar — last 4 digits only", placeholder: "1234", hint: "We never store the full number", attrs: { pattern: "[0-9]{4}", maxLength: 4, inputMode: "numeric" } },
    ],
  },
  {
    id: "home",
    title: "Home & category",
    blurb: "Most scholarships depend on where you live, your category and family income.",
    fields: [
      { key: "domicile_state", label: "Domicile state", placeholder: "Maharashtra" },
      { key: "district", label: "District", placeholder: "e.g. Pune" },
      { key: "taluka", label: "Taluka", placeholder: "e.g. Haveli" },
      { key: "category", label: "Category", type: "select", options: ["Open", "OBC", "SC", "ST", "VJ/NT", "SBC", "SEBC", "EWS"] },
      { key: "caste", label: "Caste", placeholder: "As written on your caste certificate" },
      { key: "religion", label: "Religion", placeholder: "Optional" },
      { key: "annual_family_income", label: "Annual family income (₹)", type: "number", placeholder: "e.g. 148000", hint: "As on your income certificate", attrs: { min: 0, step: 1 }, wide: true },
    ],
  },
  {
    id: "education",
    title: "Education",
    blurb: "Your past results and what you're studying now.",
    fields: [
      { key: "ssc_board", label: "10th board", placeholder: "e.g. Maharashtra State Board" },
      { key: "ssc_year", label: "10th passing year", type: "number", attrs: YEAR },
      { key: "ssc_percentage", label: "10th percentage", type: "number", attrs: PCT },
      { key: "hsc_board", label: "12th board", placeholder: "e.g. Maharashtra State Board" },
      { key: "hsc_year", label: "12th passing year", type: "number", attrs: YEAR },
      { key: "hsc_percentage", label: "12th percentage", type: "number", attrs: PCT },
      { key: "current_course", label: "Current course", placeholder: "e.g. B.E. Computer Engineering" },
      { key: "current_year", label: "Year of study", type: "select", options: ["1", "2", "3", "4", "5", "6"] },
      {
        key: "entry_qualification",
        label: "Joined this course after",
        type: "select",
        options: ["ssc", "hsc", "diploma", "graduation"],
        labels: { ssc: "10th (diploma, ITI, 11th–12th)", hsc: "12th", diploma: "A diploma", graduation: "A degree" },
        hint: "Decides which results apply: 12th details are skipped if you came after 10th or a diploma",
      },
      { key: "admission_year", label: "Year of admission", type: "number", attrs: YEAR },
      {
        key: "course_mode",
        label: "Course mode",
        type: "select",
        options: ["regular", "part_time", "distance", "online"],
        labels: { regular: "Regular (full-time)", part_time: "Part-time", distance: "Distance / correspondence", online: "Online" },
      },
      { key: "institute_name", label: "College / institute", placeholder: "Full name of your college", wide: true },
    ],
  },
] as const satisfies readonly { id: string; title: string; blurb: string; fields: readonly Field[] }[];

export type SectionId = (typeof SECTIONS)[number]["id"];
export const ALL_FIELDS: readonly Field[] = SECTIONS.flatMap((s): readonly Field[] => s.fields);

export function completion(p: ProfileDraft | null | undefined): number {
  if (!p) return 0;
  return Math.round((ALL_FIELDS.filter((f) => p[f.key]?.trim()).length / ALL_FIELDS.length) * 100);
}

export type FieldSource = { source_type: string; confirmed_at: string };
const SOURCE_TEXT: Record<string, string> = {
  manual: "Typed by you",
  text: "From your chat",
  voice: "Said to Aster",
  document: "From your document",
  aadhaar_qr: "From Aadhaar QR",
};

/** Where a saved value came from (guardrail 2), e.g. "From your document · 4 Oct". */
function SourceChip({ src }: { src: FieldSource }) {
  const when = new Date(src.confirmed_at).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
  return (
    <span className="chip ml-auto text-xs font-normal text-muted-foreground">
      {SOURCE_TEXT[src.source_type] ?? src.source_type} · {when}
    </span>
  );
}

export function ProfileFields({
  section,
  value,
  onChange,
  readOnly,
  sources,
}: {
  section: SectionId;
  value: ProfileDraft;
  onChange: (next: ProfileDraft) => void;
  readOnly?: boolean;
  /** Saved sources per field; a chip shows next to fields still holding their saved value. */
  sources?: Partial<Record<ProfileKey, FieldSource & { value: string }>>;
}) {
  const fields: readonly Field[] = SECTIONS.find((s) => s.id === section)!.fields;
  return (
    <div className="grid gap-x-4 gap-y-5 sm:grid-cols-2">
      {fields.map((f) => {
        const id = `pf-${f.key}`;
        const v = value[f.key] ?? "";
        const set = (x: string) => onChange({ ...value, [f.key]: x });
        return (
          <div key={f.key} className={cn("flex flex-col gap-1.5", f.wide && "sm:col-span-2")}>
            <div className="flex items-center gap-2">
              <label htmlFor={id} className="text-sm font-medium">
                {f.label}
              </label>
              {sources?.[f.key] && sources[f.key]!.value === v && v !== "" && <SourceChip src={sources[f.key]!} />}
            </div>
            {f.type === "select" ? (
              <select id={id} value={v} disabled={readOnly} onChange={(e) => set(e.target.value)} className="field disabled:bg-muted">
                <option value="">Select…</option>
                {f.options?.map((o) => (
                  <option key={o} value={o}>
                    {f.labels?.[o] ?? o}
                  </option>
                ))}
              </select>
            ) : (
              <input
                id={id}
                type={f.type ?? "text"}
                value={v}
                readOnly={readOnly}
                placeholder={f.placeholder}
                onChange={(e) => set(e.target.value)}
                className="field read-only:bg-muted"
                {...f.attrs}
              />
            )}
            {f.hint && <span className="text-xs text-muted-foreground">{f.hint}</span>}
          </div>
        );
      })}
    </div>
  );
}
