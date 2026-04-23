'use client';

import { Memory } from '@/lib/types';
import { Card, CardContent } from '@/engine/components/ui/card';
import { Badge } from '@/engine/components/ui/badge';

interface MemoryCardProps {
  memory: Memory;
}

export function MemoryCard({ memory }: MemoryCardProps) {
  const createdDate = new Date(memory.created_at * 1000).toLocaleDateString('ko-KR');
  const updatedDate = new Date(memory.updated_at * 1000).toLocaleDateString('ko-KR');

  return (
    <Card>
      <CardContent className="pt-4">
        <p className="text-sm text-text-primary line-clamp-2 mb-3 leading-relaxed">
          {memory.content}
        </p>

        {memory.tags.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mb-3">
            {memory.tags.map((tag) => (
              <Badge key={tag} variant="outline">
                {tag}
              </Badge>
            ))}
          </div>
        )}

        <div className="flex items-center justify-between text-xs text-text-tertiary">
          <span>생성: {createdDate}</span>
          {memory.updated_at !== memory.created_at && (
            <span>수정: {updatedDate}</span>
          )}
          {memory.score !== undefined && (
            <Badge variant="secondary">
              score: {memory.score.toFixed(3)}
            </Badge>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
