import { describe, it, expect } from 'vitest';

// Test the command-matching logic that admin.ts uses.
// We extract the matching into pure functions for testability.
// FIX S8: now supports @bot suffix.

function matchCommand(text: string): {
  isAimode: boolean;
  isIntercepts: boolean;
  isAudit: boolean;
  isBan: boolean;
  isModel: boolean;
  isTo: boolean;
  isAi: boolean;
} {
  return {
    isAimode: text === '/aimode' || text.startsWith('/aimode ') || text.startsWith('/aimode@'),
    isIntercepts: text === '/intercepts' || text.startsWith('/intercepts ') || text.startsWith('/intercepts@'),
    isAudit: text === '/audit' || text.startsWith('/audit ') || text.startsWith('/audit@'),
    isBan: /^\/(?:ban|unban|block|unblock|forgive)(?:@\w+)?(?:\s|$)/.test(text),
    isModel: text === '/model' || text.startsWith('/model ') || text.startsWith('/model@'),
    isTo: text === '/to' || text.startsWith('/to ') || text.startsWith('/to@'),
    isAi: text === '/ai' || text.startsWith('/ai ') || text.startsWith('/ai@'),
  };
}

describe('admin command matching (S4/S5 fix)', () => {
  describe('exact command matching', () => {
    it('matches /aimode exactly', () => {
      expect(matchCommand('/aimode').isAimode).toBe(true);
      expect(matchCommand('/aimode on').isAimode).toBe(true);
      expect(matchCommand('/aimode off').isAimode).toBe(true);
    });

    it('does NOT match /aimodes or /aimodex', () => {
      expect(matchCommand('/aimodes').isAimode).toBe(false);
      expect(matchCommand('/aimodex').isAimode).toBe(false);
      expect(matchCommand('/aimode123').isAimode).toBe(false);
    });
  });

  describe('/ban family — does NOT match /bank, /banned, etc.', () => {
    it('matches /ban with space or end', () => {
      expect(matchCommand('/ban').isBan).toBe(true);
      expect(matchCommand('/ban 12345').isBan).toBe(true);
      expect(matchCommand('/unban 12345').isBan).toBe(true);
      expect(matchCommand('/block 12345').isBan).toBe(true);
      expect(matchCommand('/unblock 12345').isBan).toBe(true);
      expect(matchCommand('/forgive 12345').isBan).toBe(true);
    });

    it('does NOT match /bank, /banned, /blocks', () => {
      expect(matchCommand('/bank').isBan).toBe(false);
      expect(matchCommand('/bank account').isBan).toBe(false);
      expect(matchCommand('/banned').isBan).toBe(false);
      expect(matchCommand('/blocks').isBan).toBe(false);
      expect(matchCommand('/forgiveness').isBan).toBe(false);
      expect(matchCommand('/unblockchain').isBan).toBe(false);
    });
  });

  describe('/model — does NOT match /modeling, /models', () => {
    it('matches /model exactly', () => {
      expect(matchCommand('/model').isModel).toBe(true);
      expect(matchCommand('/model list').isModel).toBe(true);
      expect(matchCommand('/model gpt-4').isModel).toBe(true);
      expect(matchCommand('/model default').isModel).toBe(true);
    });

    it('does NOT match /modeling, /models, /modelx', () => {
      expect(matchCommand('/modeling').isModel).toBe(false);
      expect(matchCommand('/models').isModel).toBe(false);
      expect(matchCommand('/modelx').isModel).toBe(false);
      expect(matchCommand('/modeling clay').isModel).toBe(false);
    });
  });

  describe('/ai — does NOT match /airplane, /aid, /aids', () => {
    it('matches /ai exactly', () => {
      expect(matchCommand('/ai').isAi).toBe(true);
      expect(matchCommand('/ai 你好').isAi).toBe(true);
      expect(matchCommand('/ai write a poem').isAi).toBe(true);
    });

    it('does NOT match /airplane, /aid, /aids', () => {
      expect(matchCommand('/airplane').isAi).toBe(false);
      expect(matchCommand('/aid').isAi).toBe(false);
      expect(matchCommand('/aids').isAi).toBe(false);
      expect(matchCommand('/airdrop').isAi).toBe(false);
    });
  });

  describe('/to — does NOT match /today, /tomorrow', () => {
    it('matches /to exactly', () => {
      expect(matchCommand('/to').isTo).toBe(true);
      expect(matchCommand('/to 12345 hello').isTo).toBe(true);
    });

    it('does NOT match /today, /tomorrow, /tool', () => {
      expect(matchCommand('/today').isTo).toBe(false);
      expect(matchCommand('/tomorrow').isTo).toBe(false);
      expect(matchCommand('/tool').isTo).toBe(false);
      expect(matchCommand('/total').isTo).toBe(false);
    });
  });

  describe('/intercepts — does NOT match /interceptsextra', () => {
    it('matches /intercepts exactly', () => {
      expect(matchCommand('/intercepts').isIntercepts).toBe(true);
      expect(matchCommand('/intercepts 10').isIntercepts).toBe(true);
    });

    it('does NOT match /interceptsx', () => {
      expect(matchCommand('/interceptsx').isIntercepts).toBe(false);
      expect(matchCommand('/interceptsfoo').isIntercepts).toBe(false);
    });
  });

  describe('/audit — does NOT match /auditor, /audition', () => {
    it('matches /audit exactly', () => {
      expect(matchCommand('/audit').isAudit).toBe(true);
      expect(matchCommand('/audit 50').isAudit).toBe(true);
    });

    it('does NOT match /auditor, /audition', () => {
      expect(matchCommand('/auditor').isAudit).toBe(false);
      expect(matchCommand('/audition').isAudit).toBe(false);
    });
  });

  describe('non-command text does not match any', () => {
    it('plain text matches nothing', () => {
      const m = matchCommand('hello world');
      expect(m.isAimode).toBe(false);
      expect(m.isIntercepts).toBe(false);
      expect(m.isAudit).toBe(false);
      expect(m.isBan).toBe(false);
      expect(m.isModel).toBe(false);
      expect(m.isTo).toBe(false);
      expect(m.isAi).toBe(false);
    });
  });

  describe('@bot suffix support (S8 fix)', () => {
    it('matches /ban@mybot', () => {
      expect(matchCommand('/ban@mybot').isBan).toBe(true);
      expect(matchCommand('/ban@mybot 12345').isBan).toBe(true);
      expect(matchCommand('/unban@mybot 12345').isBan).toBe(true);
      expect(matchCommand('/forgive@mybot 12345').isBan).toBe(true);
    });

    it('matches /model@mybot', () => {
      expect(matchCommand('/model@mybot').isModel).toBe(true);
      expect(matchCommand('/model@mybot list').isModel).toBe(true);
    });

    it('matches /ai@mybot', () => {
      expect(matchCommand('/ai@mybot').isAi).toBe(true);
      expect(matchCommand('/ai@mybot 你好').isAi).toBe(true);
    });

    it('matches /to@mybot', () => {
      expect(matchCommand('/to@mybot').isTo).toBe(true);
      expect(matchCommand('/to@mybot 12345 hello').isTo).toBe(true);
    });

    it('matches /aimode@mybot', () => {
      expect(matchCommand('/aimode@mybot').isAimode).toBe(true);
      expect(matchCommand('/aimode@mybot on').isAimode).toBe(true);
    });

    it('matches /intercepts@mybot and /audit@mybot', () => {
      expect(matchCommand('/intercepts@mybot').isIntercepts).toBe(true);
      expect(matchCommand('/intercepts@mybot 10').isIntercepts).toBe(true);
      expect(matchCommand('/audit@mybot').isAudit).toBe(true);
      expect(matchCommand('/audit@mybot 50').isAudit).toBe(true);
    });
  });
});
