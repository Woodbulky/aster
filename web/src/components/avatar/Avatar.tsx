"use client";

import { motion, useReducedMotion } from "framer-motion";
import { useEffect, useId, useState } from "react";

type AvatarSpec = {
  name: string;
  body: string;
  glow: string;
  eye: { rx: number; ry: number };
  cheeks?: boolean;
};

export const AVATARS = {
  aster: { name: "Aster", body: "#0f766e", glow: "#5eead4", eye: { rx: 6, ry: 8 } },
  mitra: { name: "Mitra", body: "#f28c28", glow: "#fed7aa", eye: { rx: 5, ry: 10 } },
  tara: { name: "Tara", body: "#4338ca", glow: "#c7d2fe", eye: { rx: 8, ry: 6 } },
  chintu: { name: "Chintu", body: "#15803d", glow: "#bbf7d0", eye: { rx: 4.5, ry: 5.5 }, cheeks: true },
} satisfies Record<string, AvatarSpec>;
export type AvatarId = keyof typeof AVATARS;
export const AVATAR_IDS = Object.keys(AVATARS) as AvatarId[];

const center = { transformBox: "fill-box", transformOrigin: "center" } as const;

/** Orb-with-eyes avatar. Idle state only for now: slow breathe + a blink every 3–6 s. */
export function Avatar({ id, size = 128 }: { id: AvatarId; size?: number }) {
  const spec: AvatarSpec = AVATARS[id];
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

  const loop = { duration: 4, repeat: Infinity, ease: "easeInOut" } as const;

  return (
    <svg viewBox="0 0 120 120" width={size} height={size} role="img" aria-label={spec.name}>
      <defs>
        <radialGradient id={gid} cx="35%" cy="30%" r="75%">
          <stop offset="0%" stopColor={spec.glow} />
          <stop offset="45%" stopColor={spec.body} />
          <stop offset="100%" stopColor={spec.body} stopOpacity={0.9} />
        </radialGradient>
      </defs>
      <motion.circle
        cx={60}
        cy={60}
        r={54}
        fill={spec.glow}
        style={center}
        animate={reduce ? undefined : { opacity: [0.35, 0.6, 0.35], scale: [0.96, 1.02, 0.96] }}
        transition={loop}
        opacity={0.45}
      />
      <motion.g style={center} animate={reduce ? undefined : { scale: [1, 1.04, 1], y: [0, -2, 0] }} transition={loop}>
        <circle cx={60} cy={60} r={44} fill={`url(#${gid})`} />
        <motion.g style={center} animate={{ scaleY: blink ? 0.1 : 1 }} transition={{ duration: 0.07 }}>
          {[44, 76].map((cx) => (
            <g key={cx}>
              <ellipse cx={cx} cy={56} rx={spec.eye.rx} ry={spec.eye.ry} fill="#fbf8f3" />
              <circle cx={cx + 1} cy={57} r={Math.min(spec.eye.rx, spec.eye.ry) * 0.5} fill="#14213d" />
            </g>
          ))}
        </motion.g>
        {spec.cheeks &&
          [34, 86].map((cx) => <circle key={cx} cx={cx} cy={70} r={6} fill="#fda4af" opacity={0.6} />)}
        <path d="M52 76 Q60 82 68 76" stroke="#fbf8f3" strokeWidth={3} strokeLinecap="round" fill="none" />
      </motion.g>
    </svg>
  );
}
