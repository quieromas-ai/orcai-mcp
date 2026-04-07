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
