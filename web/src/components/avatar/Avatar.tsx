"use client";

import { motion, useReducedMotion } from "framer-motion";
import { useEffect, useId, useState } from "react";

type AvatarSpec = {
  name: string;
  tagline: string;
  light: string;
  mid: string;
  dark: string;
  eye: string;
  eyeShape: { rx: number; ry: number };
  cheeks?: boolean;
};

export const AVATARS = {
  aster: { name: "Aster", tagline: "The gentle guide", light: "#d9edb3", mid: "#95b975", dark: "#528557", eye: "#31492d", eyeShape: { rx: 4.2, ry: 6 } },
  mitra: { name: "Mitra", tagline: "The curious friend", light: "#ffd6ac", mid: "#eda574", dark: "#c87552", eye: "#6d4431", eyeShape: { rx: 4, ry: 6.8 }, cheeks: true },
  tara: { name: "Tara", tagline: "The clear thinker", light: "#e1d8ff", mid: "#b4a1dc", dark: "#8070b6", eye: "#4f426f", eyeShape: { rx: 5, ry: 4.4 } },
  chintu: { name: "Chintu", tagline: "The happy helper", light: "#fff0b7", mid: "#e3ca76", dark: "#c1a555", eye: "#6d5d2f", eyeShape: { rx: 4.6, ry: 5.4 }, cheeks: true },
} satisfies Record<string, AvatarSpec>;
export type AvatarId = keyof typeof AVATARS;
export const AVATAR_IDS = Object.keys(AVATARS) as AvatarId[];
export const isAvatarId = (v: unknown): v is AvatarId => AVATAR_IDS.includes(v as AvatarId);

const center = { transformBox: "fill-box", transformOrigin: "center" } as const;

/** Soft orb with a face. Idle state: slow breathe + a blink every 3–6 s. Other states arrive with voice (M4). */
export function Avatar({ id, size = 128 }: { id: string; size?: number }) {
  const spec: AvatarSpec = AVATARS[isAvatarId(id) ? id : "aster"];
  const reduce = useReducedMotion();
  const gid = useId();
  const [blink, setBlink] = useState(false);

  useEffect(() => {
    if (reduce) return;
    let timer: number;
    const schedule = () => {
      timer = window.setTimeout(() => {
        setBlink(true);
        timer = window.setTimeout(() => {
          setBlink(false);
          schedule();
        }, 140);
      }, 3000 + Math.random() * 3000);
    };
    schedule();
    return () => window.clearTimeout(timer);
  }, [reduce]);

  const loop = { duration: 5, repeat: Infinity, ease: "easeInOut" } as const;

  return (
    <svg viewBox="0 0 120 120" width={size} height={size} role="img" aria-label={spec.name} className="shrink-0 overflow-visible">
      <defs>
        <radialGradient id={`${gid}b`} cx="30%" cy="24%" r="85%">
          <stop offset="0%" stopColor={spec.light} />
          <stop offset="50%" stopColor={spec.mid} />
          <stop offset="100%" stopColor={spec.dark} />
        </radialGradient>
        <radialGradient id={`${gid}h`}>
          <stop offset="0%" stopColor={spec.mid} stopOpacity={0.35} />
          <stop offset="100%" stopColor={spec.mid} stopOpacity={0} />
        </radialGradient>
      </defs>
      <circle cx={60} cy={64} r={58} fill={`url(#${gid}h)`} />
      <motion.g style={center} animate={reduce ? undefined : { scale: [1, 1.035, 1], y: [0, -1.5, 0] }} transition={loop}>
        <ellipse cx={60} cy={60} rx={47} ry={46} fill={`url(#${gid}b)`} />
        <ellipse cx={42} cy={34} rx={13} ry={7} fill="#fff" opacity={0.18} transform="rotate(-30 42 34)" />
        <motion.g style={center} animate={{ scaleY: blink ? 0.1 : 1 }} transition={{ duration: 0.07 }}>
          {[49, 71].map((cx) => (
            <g key={cx}>
              <ellipse cx={cx} cy={58} rx={spec.eyeShape.rx} ry={spec.eyeShape.ry} fill={spec.eye} />
              <circle cx={cx + 1.4} cy={55.5} r={1.3} fill="#fffbea" opacity={0.75} />
            </g>
          ))}
        </motion.g>
        {spec.cheeks &&
          [38, 82].map((cx) => <ellipse key={cx} cx={cx} cy={70} rx={5.5} ry={3} fill="#f6a99b" opacity={0.45} />)}
        <path d="M55 73 Q60 77.5 65 73" stroke={spec.eye} strokeWidth={2} strokeLinecap="round" fill="none" opacity={0.7} />
      </motion.g>
    </svg>
  );
}

/** Six-petal brand mark (from the design reference). */
export function AsterMark({ size = 28, className }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" aria-hidden="true" className={className}>
      <g fill="currentColor">
        {[0, 60, 120].map((r) => (
          <ellipse key={r} cx="20" cy="20" rx="5.4" ry="18" transform={`rotate(${r} 20 20)`} />
        ))}
      </g>
      <circle cx="20" cy="20" r="3.5" fill="var(--background)" />
    </svg>
  );
}
