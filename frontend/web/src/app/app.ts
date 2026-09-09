import { Component, OnDestroy, inject, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Api, Correcao, ItemBiblioteca, Provider, Stats } from './api';

type Tela = 'inicio' | 'biblioteca' | 'correcoes';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class App implements OnDestroy {
  private api = inject(Api);

  tela = signal<Tela>('inicio');
  stats = signal<Stats | null>(null);
  biblioteca = signal<ItemBiblioteca[]>([]);
  correcoes = signal<Correcao[]>([]);
  busca = signal('');
  carregando = signal(false);
  erro = signal<string | null>(null);

  /** Provedor escolhido nesta sessão de sync; some o botão do outro. */
  provedorAtivo = signal<Provider | null>(null);
  rodando = signal(false);
  etapa = signal('');
  progresso = signal({ feito: 0, total: 0 });
  ultimoResultado = signal<Record<string, any> | null>(null);

  private timer?: ReturnType<typeof setInterval>;

  constructor() {
    this.recarregarStats();
    // se uma tarefa já estiver rodando (recarreguei a página no meio), reengata
    this.api.tarefa().subscribe((t) => {
      if (t.rodando) {
        this.rodando.set(true);
        this.provedorAtivo.set(this.provedorDe(t.tipo));
        this.acompanhar();
      }
    });
  }

  ngOnDestroy() {
    clearInterval(this.timer);
  }

  private provedorDe(tipo: string | null): Provider | null {
    return tipo === 'anilist' || tipo === 'mal' ? tipo : null;
  }

  rotuloProvedor(p: Provider): string {
    return p === 'mal' ? 'MyAnimeList' : 'AniList';
  }

  /** Botão do outro provedor some enquanto um sync está escolhido/rodando. */
  mostraProvedor(p: Provider): boolean {
    const ativo = this.provedorAtivo();
    return ativo === null || ativo === p;
  }

  recarregarStats() {
    this.api.stats().subscribe({
      next: (s) => this.stats.set(s),
      error: () => this.erro.set('não consegui falar com o servidor'),
    });
  }

  abrirBiblioteca() {
    this.tela.set('biblioteca');
    this.carregando.set(true);
    this.api.biblioteca(this.busca()).subscribe({
      next: (itens) => {
        this.biblioteca.set(itens);
        this.carregando.set(false);
      },
      error: (e) => {
        this.erro.set(`falha ao carregar: ${e.message}`);
        this.carregando.set(false);
      },
    });
  }

  voltar() {
    this.tela.set('inicio');
    this.erro.set(null);
    this.recarregarStats();
  }

  baixarCrunchyroll() {
    this.disparar(() => this.api.baixarCrunchyroll(false), null);
  }

  sincronizar(provider: Provider) {
    this.provedorAtivo.set(provider);
    this.disparar(() => this.api.sincronizarProvedor(provider), provider);
  }

  private disparar(chamada: () => any, provider: Provider | null) {
    this.erro.set(null);
    this.rodando.set(true);
    this.ultimoResultado.set(null);
    chamada().subscribe({
      next: () => this.acompanhar(),
      error: (e: any) => {
        const corpo = e?.error ?? {};
        if (e?.status === 429 && confirm(
          `Sincronizado há pouco (libera em ${corpo.minutos_ate_liberar} min). Baixar mesmo assim?`)) {
          this.api.baixarCrunchyroll(true).subscribe(() => this.acompanhar());
          return;
        }
        this.erro.set(corpo.erro ?? `falha ao iniciar (${e?.status})`);
        this.rodando.set(false);
        if (provider) this.provedorAtivo.set(null);
      },
    });
  }

  private acompanhar() {
    clearInterval(this.timer);
    this.timer = setInterval(() => {
      this.api.tarefa().subscribe((t) => {
        this.etapa.set(t.etapa);
        this.progresso.set({ feito: t.feito, total: t.total });
        if (t.rodando) return;

        clearInterval(this.timer);
        this.rodando.set(false);
        this.etapa.set('');
        if (t.erro) this.erro.set(t.erro);
        this.ultimoResultado.set(t.resultado);
        this.recarregarStats();

        // ao fim do sync de um provedor, mostra só o que precisa de correção
        const provider = this.provedorDe(t.tipo);
        if (!t.erro && provider) this.abrirCorrecoes(provider);
      });
    }, 1000);
  }

  abrirCorrecoes(provider: Provider) {
    this.tela.set('correcoes');
    this.carregando.set(true);
    this.api.correcoes(provider, this.busca()).subscribe({
      next: (itens) => {
        this.correcoes.set(itens);
        this.carregando.set(false);
      },
      error: () => this.carregando.set(false),
    });
  }

  decidir(item: Correcao, status: string, idDigitado: string) {
    const id = idDigitado ? Number(idDigitado) : undefined;
    this.api.revisar(item.season_id, status, id).subscribe({
      next: () => {
        this.correcoes.update((lista) => lista.filter((x) => x.season_id !== item.season_id));
        this.recarregarStats();
      },
      error: (e) => this.erro.set(e?.error?.erro ?? 'não foi possível salvar'),
    });
  }

  etiquetas = computed(() => (item: ItemBiblioteca) => item.providers.split(','));

  temVinculo(item: ItemBiblioteca, p: Provider): boolean {
    return item.providers.split(',').includes(p);
  }
}
