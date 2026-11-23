// Source-local canonical ranking, followed by exact first-conflict, zero-first DFS.
#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <iostream>
#include <limits>
#include <memory>
#include <stdexcept>
#include <unordered_map>
#include <vector>

using Word = std::uint64_t;
using Bits = std::array<Word,4>;
using Digits = std::array<Word,8>;  // 128 four-bit chronological slots; 0 denotes omission.
constexpr int width = 10;
constexpr int impossible = -1000000000;

struct Fix {
    Bits zero{}, one{};
    bool operator==(const Fix& b) const { return zero == b.zero && one == b.one; }
};
struct Hash {
    size_t operator()(const Fix& f) const {
        Word h = 0x9e3779b97f4a7c15ULL;
        for (const Bits* m : {&f.zero,&f.one}) for (Word w : *m)
            h ^= w + 0x9e3779b97f4a7c15ULL + (h<<6) + (h>>2);
        return h;
    }
};
struct Difference { int position; bool prefer_first; };
class Area;
class PrivateSelection { friend class Area; Digits digits{}; };
using Handle = std::shared_ptr<const PrivateSelection>;
struct Reply { int score = -1; Bits interface{}; Handle handle; };
struct Option { int points=0, grant=0, require=0, forbidden=0, projection=-1; };
struct Interval { int global=0; std::array<Option,width> options{}; unsigned allowed=0; };

class Area {
    int states;
    std::vector<Interval> intervals;
    std::vector<std::pair<int,int>> public_positions;
    std::unordered_map<Fix,Reply,Hash> cache;
    std::vector<unsigned> allowed;
    std::vector<unsigned char> selected, choices;
    std::vector<int> after, before;

    Reply solve(const Fix& f) {
        for (size_t i=0;i<intervals.size();++i) allowed[i]=intervals[i].allowed;
        for (int block=0;block<4;++block) {
            Word zero=f.zero[block], one=f.one[block];
            while (zero) {
                int bit=__builtin_ctzll(zero);
                auto [i,k]=public_positions.at(64*block+bit);
                allowed[i]&=~(1u<<k);
                zero&=zero-1;
            }
            while (one) {
                int bit=__builtin_ctzll(one);
                auto [i,k]=public_positions.at(64*block+bit);
                // The omission bit is removed as well. Two distinct forced choices cannot coexist.
                allowed[i]&=(1u<<k);
                if (!allowed[i]) return {};
                one&=one-1;
            }
        }
        // Each interval's candidates are in decreasing sensor score and rank.
        // These separate winners simultaneously maximize all tie levels if they meet the local prerequisites.
        int state=0, total=0;
        bool independent=true;
        for (size_t i=0;i<intervals.size();++i) {
            if (!allowed[i]) return {};
            int k=__builtin_ctz(allowed[i]);
            selected[i]=k;
            if (k==width) continue;
            const Option& c=intervals[i].options[k];
            if ((state&c.require)!=c.require) {independent=false; break;}
            state|=c.grant; total+=c.points;
        }
        if (!independent) {
            // Suffix DP. An equal additive score is broken locally by the first (highest-ranked)
            // available choice, after which the already canonical continuation resolves later intervals.
            std::fill(after.begin(),after.end(),0);
            for (int i=static_cast<int>(intervals.size())-1;i>=0;--i) {
                for (int s=0;s<states;++s) {
                    int best=impossible, pick=width;
                    for (unsigned options=allowed[i];options;options&=options-1) {
                        int k=__builtin_ctz(options), value=after[s];
                        if (k!=width) {
                            const Option& c=intervals[i].options[k];
                            if ((s&c.require)!=c.require) continue;
                            int next=after[s|c.grant];
                            if (next==impossible) continue;
                            value=c.points+next;
                        }
                        if (value>best) {best=value; pick=k;}
                    }
                    before[s]=best;
                    choices[i*states+s]=pick;
                }
                after.swap(before);
            }
            if (after[0]==impossible) return {};
            total=after[0]; state=0;
            for (size_t i=0;i<intervals.size();++i) {
                int k=choices[i*states+state];
                selected[i]=k;
                if (k!=width) state|=intervals[i].options[k].grant;
            }
        }
        auto stored=std::make_shared<PrivateSelection>();
        Reply out;out.score=total; out.handle=stored;
        for (size_t i=0;i<intervals.size();++i) {
            int k=selected[i];
            if (k==width) continue;
            int g=intervals[i].global, j=intervals[i].options[k].projection;
            stored->digits[g/16] |= Word(width-k)<<(60-4*(g%16));
            if (j>=0) out.interface[j/64] |= Word{1}<<(j%64);
        }
        return out;
    }
public:
    Word solves=0;
    Area(std::vector<Interval> obs,int support_bits):states(1<<support_bits),intervals(std::move(obs)),
        allowed(intervals.size()),selected(intervals.size()),choices(intervals.size()*states),after(states),before(states) {}
    void register_projection(const std::vector<int>& globals) {
        for (int g:globals) {
            int t=g/width,k=g%width;
            auto it=std::lower_bound(intervals.begin(),intervals.end(),t,
                [](const Interval& a,int b){return a.global<b;});
            if (it==intervals.end() || it->global!=t || public_positions.size()>=256)
                throw std::logic_error("unknown public candidate or too many interface bits");
            it->options[k].projection=public_positions.size();
            public_positions.emplace_back(it-intervals.begin(),k);
        }
    }
    Reply reply(const Fix& f) {
        auto it=cache.find(f);
        if (it!=cache.end()) return it->second;
        ++solves;
        Reply r=solve(f);
        if (cache.size()>=131072) cache.clear();  // Live and retained opaque handles stay valid.
        cache.emplace(f,r);
        return r;
    }
    Difference compare(const Handle& a,const Handle& b) const {
        for (size_t w=0;w<Digits{}.size();++w) {
            Word delta=a->digits[w]^b->digits[w];
            if (delta) return {static_cast<int>(16*w+__builtin_clzll(delta)/4),a->digits[w]>b->digits[w]};
        }
        return {std::numeric_limits<int>::max(),false};
    }
    void emit(const Handle& h,std::vector<int>& ranks) const {
        for (const auto& o:intervals) ranks[o.global]=
            (h->digits[o.global/16]>>(60-4*(o.global%16)))&15;
    }
};

struct Term { int row, sign; };
struct Row { int minimum=0,lhs=0,limit=0; std::vector<int> positive,negative; };
struct Port { Fix fixed; Reply latest; std::vector<int> globals; Handle retained; };

class Coordinator {
    std::vector<Area>& sites;
    std::vector<Port> ports;
    std::vector<Row> rows;
    std::vector<std::vector<Term>> terms;
    std::vector<int> owner, local;
    std::vector<unsigned char> fixed, selected;
    std::vector<Word> violated;
    int contradictions=0;
    std::chrono::steady_clock::time_point start=std::chrono::steady_clock::now();
    void mark(int r,bool on) {
        Word bit=Word{1}<<(r%64); if(on) violated[r/64]|=bit; else violated[r/64]&=~bit;
    }
    void install(int s,const Reply& v) {
        Port& p=ports[s];
        for (size_t b=0;b<v.interface.size();++b) {
            Word delta=p.latest.interface[b]^v.interface[b];
            while(delta) {
                int k=__builtin_ctzll(delta), g=p.globals[64*b+k];
                bool on=(v.interface[b]>>k)&1;
                selected[g]=on;
                for (Term t:terms[g]) {
                    Row& r=rows[t.row]; r.lhs+=on?t.sign:-t.sign; mark(t.row,r.lhs>r.limit);
                }
                delta&=delta-1;
            }
        }
        p.latest=v;
    }
    bool improves(int score) {
        if(score!=best) return score>best;
        ++lex_checks;
        Difference first{std::numeric_limits<int>::max(),false};
        // Include changes at every source, including ones installed in ancestor or earlier DFS branches.
        for(size_t s=0;s<ports.size();++s) if(ports[s].latest.handle!=ports[s].retained) {
            Difference d=sites[s].compare(ports[s].latest.handle,ports[s].retained);
            ++lex_source_comparisons;
            if(d.position<first.position) first=d;
        }
        return first.prefer_first;
    }
    int conflict() const {
        for(size_t w=0;w<violated.size();++w) if(violated[w]) {
            const Row& r=rows[64*w+__builtin_ctzll(violated[w])];
            for(int g:r.positive) if(!fixed[g] && selected[g]) return g;
            for(int g:r.negative) if(!fixed[g] && !selected[g]) return g;
            throw std::logic_error("conflict does not have a free candidate");
        }
        return -1;
    }
    void fixing(int g,bool value,bool add) {
        Port& p=ports[owner[g]]; int j=local[g];
        (value?p.fixed.one:p.fixed.zero)[j/64]^=Word{1}<<(j%64); fixed[g]=add;
        for(Term t:terms[g]) if((t.sign>0)==value) {
            Row& r=rows[t.row]; int was=r.minimum; r.minimum+=add?1:-1;
            contradictions+=(r.minimum>r.limit)-(was>r.limit);
        }
    }
    void branch(int g,int bound,bool value) {
        ++nodes;
        if ((nodes&16777215)==0) std::cerr<<"nodes "<<nodes<<" best "<<best<<"\n";
        fixing(g,value,true);
        if(!contradictions && improves(bound)) {
            ++rounds;
            int s=owner[g]; Reply prior=ports[s].latest, updated=sites[s].reply(ports[s].fixed);
            if(updated.score>=0) {
                int sum=bound-prior.score+updated.score;
                if(sum>bound) throw std::logic_error("owner optimum increased under fixing");
                if(sum>=best) {
                    install(s,updated);
                    if(improves(sum)) visit(sum);
                    install(s,prior);
                }
            }
        }
        fixing(g,value,false);
    }
    void visit(int bound) {
        int g=conflict();
        if(g<0) {
            best=bound; for(auto& p:ports) p.retained=p.latest.handle;
        } else {
            branch(g,bound,false); branch(g,bound,true);
        }
    }
public:
    int best=-1;
    Word nodes=1,rounds=1,lex_checks=0,lex_source_comparisons=0;
    Coordinator(std::vector<Area>& areas,std::vector<int> candidate_owners,int nr)
        :sites(areas),ports(areas.size()),rows(nr),terms(candidate_owners.size()),owner(std::move(candidate_owners)),
         local(owner.size(),-1),fixed(owner.size()),selected(owner.size()),violated((nr+63)/64) {
        for(int i=0;i<nr;++i) {
            Row& r=rows[i]; int size;std::cin>>r.limit>>size;
            for(int k=0;k<size;++k) {
                int g,a;std::cin>>g>>a;
                if(g<0 || g>=static_cast<int>(owner.size()) || (a!=1&&a!=-1))
                    throw std::logic_error("invalid public coefficient");
                terms[g].push_back({i,a}); (a>0?r.positive:r.negative).push_back(g);
                if(a<0) --r.minimum;
            }
            contradictions+=r.minimum>r.limit; mark(i,r.lhs>r.limit);
        }
        for(size_t g=0;g<owner.size();++g) if(!terms[g].empty()) {
            auto& list=ports.at(owner[g]).globals;local[g]=list.size(); list.push_back(g);
        }
        for(size_t s=0;s<sites.size();++s) sites[s].register_projection(ports[s].globals);
    }
    bool run() {
        int sum=0;
        if(contradictions) return false;
        for(size_t s=0;s<sites.size();++s) {
            Reply r=sites[s].reply(ports[s].fixed);if(r.score<0) return false;
            sum+=r.score;install(s,r);
        }
        visit(sum);
        return best>=0;
    }
    void emit(std::vector<int>& ranks) {
        for(size_t s=0;s<sites.size();++s) sites[s].emit(ports[s].retained,ranks);
    }
};

int main() {
    int n,ns,nr; if(!(std::cin>>n>>ns>>nr) || n<1 || n>128 || ns<1) return 2;
    std::vector<Area> sites; std::vector<int> owner(n*width,-1);
    for(int s=0;s<ns;++s) {
        int count,bits;std::cin>>count>>bits;if(bits<0 || bits>8) return 2;
        std::vector<Interval> group(count);
        for(auto& o:group) {
            std::cin>>o.global; if(o.global<0 || o.global>=n) return 2;
            o.allowed=1u<<width;
            for(int k=0;k<width;++k) {
                Option& c=o.options[k];int score;
                std::cin>>score>>c.grant>>c.require>>c.forbidden;
                if(score<0 || score>181) return 2;
                c.points=score*(n+1)+(k==0);
                if(!c.forbidden) o.allowed|=1u<<k;
                owner[width*o.global+k]=s;
            }
        }
        sites.emplace_back(std::move(group),bits);
    }
    if(std::find(owner.begin(),owner.end(),-1)!=owner.end()) return 2;
    Coordinator c(sites,owner,nr); if(!std::cin || !c.run()) return 3;
    std::vector<int> ranks(n);c.emit(ranks);
    Word misses=0;for(auto& s:sites) misses+=s.solves;
    std::cout<<c.best<<" "<<c.nodes<<" "<<c.rounds<<" "<<misses<<" "<<c.lex_checks<<" "<<c.lex_source_comparisons<<"\n";
    for(int r:ranks) std::cout<<r<<" "; std::cout<<"\n";
}
