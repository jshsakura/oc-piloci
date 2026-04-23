'use client';

import { useState, KeyboardEvent } from 'react';
import { Input } from '@/engine/components/ui/input';
import { Button } from '@/engine/components/ui/button';

interface SearchBarProps {
  onSearch: (query: string) => void;
  placeholder?: string;
}

export function SearchBar({ onSearch, placeholder = '검색어를 입력하세요' }: SearchBarProps) {
  const [value, setValue] = useState('');

  const handleSearch = () => {
    onSearch(value.trim());
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      handleSearch();
    }
  };

  return (
    <div className="flex gap-2">
      <Input
        type="text"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        className="flex-1"
      />
      <Button onClick={handleSearch} size="md">
        검색
      </Button>
    </div>
  );
}
