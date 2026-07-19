/**
 * NumberField — labelled numeric input used in sync form options.
 */

type NumberFieldProps = {
  label: string
  value: number
  onChange: (value: number) => void
}

export function NumberField({ label, value, onChange }: NumberFieldProps) {
  return (
    <label>
      {label}
      <input
        min={0}
        type="number"
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </label>
  )
}
