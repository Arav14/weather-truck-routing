import { useEffect, useRef, useState } from 'react';
import { geocode } from './api.js';

export default function SearchBox({ label, placeholder, onChange }) {
  const [text, setText] = useState('');
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [picked, setPicked] = useState(false);
  const skip = useRef(false);

  useEffect(() => {
    if (skip.current) {
      skip.current = false;
      return;
    }
    if (text.trim().length < 3) {
      setItems([]);
      return;
    }
    const ctl = new AbortController();
    const t = setTimeout(async () => {
      setBusy(true);
      try {
        setItems(await geocode(text.trim(), ctl.signal));
        setOpen(true);
      } catch (e) {
        if (e.name !== 'AbortError') setItems([]);
      } finally {
        setBusy(false);
      }
    }, 350);
    return () => {
      clearTimeout(t);
      ctl.abort();
    };
  }, [text]);

  const pick = (it) => {
    skip.current = true;
    setText(it.label);
    setPicked(true);
    setOpen(false);
    onChange(it);
  };

  return (
    <label className="field search">
      <span>{label}</span>
      <input
        value={text}
        placeholder={placeholder}
        autoComplete="off"
        onChange={(e) => {
          setText(e.target.value);
          setPicked(false);
          onChange(null);
        }}
        onFocus={() => items.length && setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 120)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && open && items[0]) {
            e.preventDefault();
            pick(items[0]);
          }
        }}
      />
      {busy && <i className="spin" aria-label="Searching" />}
      {picked && <i className="ok" aria-label="Location selected">✓</i>}
      {open && items.length > 0 && (
        <ul className="suggest">
          {items.map((it, i) => (
            <li key={i} onMouseDown={() => pick(it)}>
              {it.label}
            </li>
          ))}
        </ul>
      )}
    </label>
  );
}
