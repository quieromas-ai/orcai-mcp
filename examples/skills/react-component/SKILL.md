---
name: react-component
description: Writing accessible React components
version: 1.0.0
installed_at: '2026-01-01T00:00:00+00:00'
---

# Skill: React Component

When creating a React component, follow this pattern:

```tsx
import { FC } from 'react'

interface Props {
  // Define props here
}

export const ComponentName: FC<Props> = ({ ...props }) => {
  return (
    <div className="...">
      {/* content */}
    </div>
  )
}
```

- Always use named exports
- Always define a Props interface
- Use Tailwind for styling
- Co-locate tests in `ComponentName.test.tsx`
