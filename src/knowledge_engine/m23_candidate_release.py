from __future__ import annotations

import base64
import copy
import hashlib
import json
import zlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from knowledge_engine.errors import IntegrityError

CONTRACT_SCHEMA = "knowledge-engine-m23-candidate-release-contract/v1"
RELEASE_SCHEMA = "knowledge-engine-m23-candidate-release/v1"
GRAPH_SCHEMA = "knowledge-os-graph/v2"
GRAPH_API_SCHEMA = "knowledge-engine-graph-api/v1"
SOURCE_SCHEMA = "knowledge-engine-m23-candidate-source-bundle/v1"
OVERLAY_SCHEMA = "knowledge-engine-m23-candidate-explorer-overlay/v1"
EXPECTED_ANCHOR_COUNTS = {
    "pilot/harness-theory-part-01": 29,
    "pilot/harness-theory-part-02": 40,
    "pilot/harness-theory-part-03": 38,
}
RENDERER_FIELDS = {
    "camera", "color", "coordinates", "hidden", "label_color", "layout",
    "reducer", "sigma_color", "size", "x", "y",
}
_BUNDLE_B85 = (
    "c-rk<>u(!JlK)o*`Ybv9ntu4xdJ|z2z)1|pxjWzx5dD;9O>wxxp&VV{|NW}x!5K=FI2@9SWa;*>YmuBs*Yj7^Rn>o;SUq!@)1^Q2f6"
    "k|Q;fu5U+80xO^XA`+e0K8oukI(4!cV<k_(|qY-kw|$8oxQSA{cLlS1k2HIg~m|I5p_xbi<WbdX@#hC?|_cO;QfGp%hV#UCJC|(k"
    "gBRVOU7RBym<yr@bQr6QiX=${<f!(29E_1;;++@iD>ca#{FEnCc6-<G((>`|#uB{C_^Y|Mlbf$I1CG@BaDz{D)h=n>Ziza$26e4SKrprzaPMo?lM%Je$n*%{14pdqw9QWeOgr1;Z(<)mTft6WCkHLP%52"
    "Fy)#HoEnXSLR4BRmGOpPN`i$)XS325Gd-Q;v+2#r+p<`~Bd6N<Dct{OLX#D#l6m2;GyerHn&r+<Y`&bqTjI3&d+M+Kbh7Y3$uhI`*Ncgr>g>w9)oSKN?v}R9^4UZ$%gemT%A3"
    "`fg@@JkUu0n~;eHd~`yz`xKlwb%zf8Tm0I8T=WHWyT%s#tcRKB~$@Vcva(lZNBY+fx&&^(*w<#(65nEA!xti1GjadS4;MR|ts$y=gMANmD3dCSm)zn~{?sr-8P1+MhGV<MtBU@p0mHVxWgZ9^blfN%+i5w=7d%DvLo5Tj_yH0Q$VG+=B5@)Z+T_m7lm8H0MCFMLh%mS;$uo|HFp@7Ausr2Vv!xtZ"
    "(u*-#XII|DH-dn}DYF}VT}fW>sI=%nQfkS3c&1vtOf)1{7Yau&Iq%su>ib^(%=&+`S`?M?DaUPh72XPMR0BrlRqV9r{BfjeCLHz!|vdVE&B@fm2zS)(NztVCb3;<`Zu{`apFy>ywM+4%OYGDHgj%gkK;IeG)MbXfsJjLYtBu(CJRA4qyhCG|+Agm7dnAq4D$hr3<)nJ*"
    "&ICfO_sv+s%gv?9nP5*}_=`2Q^7NsGwUd|6bl1@B`0yo?K(*i<mBrA7=prI10ANd{((5^FqHDO^|T;=-4=t^;$0sSDbWKn+}}C{>CJBDAMq)l#75AxUAGLq<|U5JlK&Ni65giGz|t%Ty?)aH>FIbf8*cVU%HD?;WTXy^j=93kvo*Xo7f<E_I"
    "5+YjY+Yh6^n^EGY=3hGHAQS6CN37r+AN(%ne0SkC8pQQk|6;4x3VN`n(DRX)``z|*i6j$vuZy;4C)s+IRVwVL|?b|rNj0To1G9$7;VO9~4A!w|fq#Z(jP6b~FM89FE_#!AIj#X2Y{z-xO8Bo>r%E^(@{QJibG6Di=irOsvtw-sJl!(|%a3Lb!TQW{D`zy<+~V8$Gn6dt"
    "UR(?|iTf(L-QFrbX2JCP##+eseoql5uZYOuwINbd~y1Oad|5z|RzG15;&D12Z}6C5n%j8U(F-0-gUph7WPKdh%7E9n79604aeR51_0Sa?n);fEy!7eEM!8AU0WYX-<0{t_r0QYZk=YlCpm@DBkZ$hdP6V=*P15Gi>YLSev>5>KUcS}T+)AUIfUub+ga;1ER+YCupKK>;&FImM1j;|O>Vd|+2<f;AB11ea"
    "Q%1_7>dWIQ!Hks`aAPyLmj-S0uRI>jd;7uHF~3^r71kOq!Hc$otAJg75u)*>)SJY|S^=MjQ%Ge#m7i_}<!?<2)lBQuH=%_8p7!gEQ8my$97c0^%igrgAa?g%%lux3)`_fms8pfWO+D#INX+R`9|q$s3HOV7sp(?9AMx(P_8nO;=?hL7(hQoMUjg&k%0E`j~R7TLV4BkXs{??0VoGv{M)25OS{KfPVXF"
    "B1!)bpml~;ay^GlB?yk%s`nEJI$g#CFNz2FE1_=oh(XirZHoXm$}WSZ&nnY%yoGgO>-OZeHR0G_FetAcW2FF7H_Uxya-~w<s$yRjug)>mk^GgtwPIEUqm{c=!-_73kYPhD}Mr%E3<MM$@ZhyZVI7!@?#yMC%^gPI<rwxI_nsp+2s-7t3M~7^Ti1IR)W0;1Gie#tqlBh=@TGT5tj-9yDxw*8rWFzBwJkiMG~(D^4y#zrJq4~pDb)X_oqpnZb=|Y&m4T6zzZeXU1f`yeK|T4VHw%QtV(CtWtA7|aq%MrgRq3;pZRj;ba69"
    "^d&At-KHL)wG}}^%F$e4>BvD!;uLzSd{l<rJ&w1dUPs%*`a+z7sr&;1>*IALzqTfoc^k?8<CGyFay!f1$NE7c)lc~SRK<`cyuyk3-DjkeG1Opn=H}UVsQ^gfK!LY)sWYb$5ZPc;-W)wfSk$Yc$4uFUQ__<1S)|#koMb?<yD*V5}w*fOj5sRw~-lmst)fW-6l}Q9|g|=nIN+5Uju%q*_&$ZK&TA*y@F#AmWK96v!@(%y1S+zSCw-R|@E^bZuY~|v|C3ujUd(K<<A!w#AFTu9<y(8Gv85pV4<crQq_#aynCw>xiHmx|GEh2}lpH96yIu9?R*3aVOZmHo$NBLWs&*w26`y"
    "roZcAQ2I%dPFf%K_o*R)ABJ1wc%sqX&CxFS8lIm^?3lnjqsqgP6~rc8TfJR*4st3V`Fx^J&NY(<C<wfECr3i%L-&g)Se%b3O!r-c^3$eV)%pF?1M`--Dq8QZoZg?BZro`l}=lm9HyYt*iN$$c+B3K~G<6=2xsL^lXt;tb1ZA`Tc4q<l}OdyjyLUjp5{0LhsAT0ZD`boa`7BS<{iLWw9<I+K"
    "HIx{rjJzMXiBQL%hdRwRJ{r2s>(cGm2HiG70;zYFjdIfE8Vo#nQ%YYnN1y3>ui!hJX!lT{EK*v;va-vwpn<B97wkH;<p99sgcWr*VgJ6t4#5Mfc#<fULt7Uj06+AY>jf2XN%NN`EE#i@r%hkzWDRd;?11`%*7HcaSscSL68LJA0{T7gbnqLA3uqTiN5^zj6?z9{`+|qqw(~xO;PN+rH~o?wz*^1Hrldyh5QhzUY7`s8(YM{bD(-IJbyE)rSBfMzXlfms6LRj?+&hg7~lg=c8CSXlHvL7H&_1ZZ(!|Caf`t3qRLI4K%BQi`s(fs>~tDz|8^Roa^PHir}jl9}H~+EZwpS"
    "<fEze+AaQ8>-kgk$e-ZVl26s!Bp;e}j^pGuLhsGVpuNDvfyFkGD+Zy73|uqk001H3har@TPQ9SMmt<Rb2<GFP%*xX`Eu)Jp#(!<to-{=b)doZz&@TYqRniX_2BOTzOSARN>sl1(K_fvhzps5p@?olH;{yAw<ldK`TNCR85$7D@-K?x5g332maYV%^m*mS50(l?9`59my4KLPbXyl>ovLNsy_ei0{7Dj%Gj{N(^k&oivusVP}_&1<zWefj4#LB=$)VDPgTE}*^N-m3Q2>ce!E=A(91>AF1r`>>ei#Y^;wRwGHkGR2}{?OR=#+v?Cj?JlUrEJ`C+N~C|sg$is>hj9Obv2C2OJSJzOlrp!LM{bKaZFL?w5"
    "FaolzOYNGr=&I5+g-mfVq6YsSZ?D88~=g+<w#L$=lg-Iz2rJmHlk$7O$?d>Ur=mpZdTVLn(y-)=Omta>RN=MM|*8HdTZ&Nn>(076Pu_^C)G$yH+1JGPbrT2k);PhL{0cf|<gSLcE@G91JWCX$&EtR#L^P$L&?It7^zt0K1`1@|tWZk6e{tPFD9`+kbs6oqR2wd@Y@PEuDNVoqR2wd@Y@PEuDNVoqR2wd@Y@PEuDM@rIUABKOrcu%BEJ!dnovMhLxAQ<uV>j3fyjFtosD3_RoqS4|Yqg0^citWk8-Tvw4i>*Lwob+7wFry5Dpa=#gacX%~^c7<qg~1+B*t#Ai_t`!oa+KcazrPPMs563wSw+WTT`<TETYK9WE_<tpW;A&&I;;`od!rjI0"
    "+&$ZzC#fa>4DE>Z@Y(Bl(@fYK_zkxdTBMIeGDT9A`QO&a`$v>9VJ++GdSO5E@x(kjZc2BxF;WcV`f{hZ#62vFnXYpcu@pJ3>IF>X%`IeDa_xyC*SB@o=&!qe1#Td(H*oku_(R}iaJTGt0`pGvH9Z3|QU{BHu-3)x{{ZaR~LkSh4jHf)%)N_|=O}w@#v0PG5f{+l^bDL_f7!Gj*h$+AeT5+U!5L})dr1|M~TT<QnV>u-lOGUs5NVt|*M!j(S0DVbCtXnI5F`4-#7>MbBDgODQ?nwIXnymLJP5qxybE|r|KUd94F1O2Q*ZYSLfRII0T+Q>>QHpl2%G<FhV8^|&9dmTU@np1(O^|te-NW)S!{e#dqZYT"
    "Hw3TG>(zg8T_QhN4m*T~Bt;DG3M(ls*nS*MQM)P=3_J23R*AdKqlKrGseGEmI?aAjOFJTCuXKrWx*o(=>wRXccXGbf}pbX27vG0!Y$Z#|fxm#`6-DdFCRaf}8R|s+Y23wiZyTJ%I(Oq5df#1HtRwnmuaI>=s-%FsjvOK=p7kx8^Cgu(yhA4QK61j8rfOj=*q3{SF+Em2uY$D^OH#>WtKO&H;_q=Y4`!=gtUD_0$-M)BhrPLoi067LOtm4HnQeJOAjS;4LzhR6()#2mqD~DL4rg3BxYukFkQT$mYSoSmqTP<|;ur`Hr`(XpGZnH!qFRu$N$C0VYu<S>q9"
    "ixDu%PR8e7z5TX_Z#EJViVLDfvsy{$FQMpJQ!m&n>5;^!ns3ZoN5`(_U9Pu)XQp(F;TACs~%xbo87KEm+pobhrD9F=R1Zrz5bOk;?-@Nj8Vj17uOgt(Pqr|HBN^Y*HzKnp2704Qv9b97*z|ecRt2As<wP<XRNk+gj@9&j4{Nq5@?JmxEP59FY>$e81%eu(`46GK5Fp1V|MWHn%Z^*jKKlT?!=xtK18i9*W2Jm80yQW?RX4ssWwT**!Q+GcZ_lG^`DP<=cZ?P+>^@<4;{4LZkO#5oc^jbc1&=ajWU0+yl3Z?HP<c1Tv!!#?1^57aIR_49iv&(>D8EI+BEjUj4(P)&(gR{KW_k91D047e(n6kqo>;2BHb|#vYlKp#<ui3zQ*t&4?E{|c6V&68u&5RAus"
    "mC)H|Y#Bg2LPh_I>28G~D6gVvZtU0WnM#xBlRr5$4;+IdyKHNwHo>-N$So};OTAET<Pa+5K-*7k>t(So+{bx(jdgr9Z8-xw+CjgS~)+MDSBV`7tjk<5Nup2syVyKdJU*tqNt?239K%NXq1))<blWBr=gF~*_pLl~2Usw!^x3{(fb;c_-g#hUuBmz2vnE_mBrC+gCzF)C3_gBo>VJ1l9`wQZBc81KGlMuLsNrm^&WjPlkq-9|mJYBU<7_KOX>A%m`qRjFfePd$@v)FR6b3B2Q~=)eV)8$+NW_I}Zn^^X#lX5h#eDA;xPjsazD$?_=vS1s#%246#h``8}3XC>qi4%YMT#@MHJ6x0~p*PCxL29d|Y^F1><PYW;Z1^{==VGj}O^3p%)dcALb525a6e1wc|(>6H<QZ&;O_T8%(V4%x<OdJ}gDjhq+7$4J3$"
    "r%#~#7>w|)Q=rBk0BtjA$QCRF0(PHXxST?FebCpj%FR>!MaJBW5jK(A$-sBfdPoMns7G;D>cpj`^LsYUNMeU*|&6kfCk2n@I4>1U7)}2dZyI&lZ;}k+dW-D@ob}2(~?=v+|(bm1*^<I``N0~h>5lSBv|LQuXg%Z%}Is+GHGjLCfUqRm##N@eZzTLG56T-WU4=@Cz*HcjbkQ__eymBI&q+M*H!g)eXri%n;ZRr_VFIETAhFmkg-O@`eNSea3eA(6|@ck2ZvHByb4Tu0*-<^Pq<_bfz7d$F&Qi~DJII`z?DQ^8m#K3z@n_4z}VMn&(Xx)u7@Ud@728+`$`|6>Hz3=Fsf4UuN#OO4L69Xu+qbOaKi$|h^1N*%u-M{nNrWVmLQ%6b52E?TE<l1@mMt-bVpPQCcjV94a267O3UqrWiMLd9xX9dgl-@v6$C6I71)8TCMjV!#WIy(2*4sUix3E&0aKu?<p!*zk}gPZQ}2CBhz}hx;R#5sN$BnA$a{?$*h0$zZt-Ap$rvUZNGS{;chC*utk#@3gT18&5QQ~_1sZ%vh2sG5LE{leDcD#IT(Jmbm}-VQQZlMUpOSay`W{m(2e|LONJ-ZXrw|)x$x^SCR!++Rv5@AVAwWhiLFE}n)EWoCS5i=XY<=*^J5C6^alpt6ru3TOL}{Oxcc;<rHJN1#F$Y8m2O}m=H&8Mqnx}?apiF8~q%9&;aAT2?ES?`|yh{zTfoYLS#85Dx{UYTmSZpozeQVh#<J!#BV^VNHe115Oqc+lzcnZEd4dBWdN~JPHK|s!g2DA#EkV3=*l;zqo1+=4<c?KT|6VLNBHA-q}2qFENX5TyU^OzbwAct`{$0Ow?W9cyEP9Ow!g`*fbQWm&3F%pnOS{nqIad7IOJ=%ICQs!J5AfhxHgI%yaza!W6yBlA5On)<A&*^YR68>)!4#EI%1@oG5EG#A|D6uD+C<0Uj<rP3mB_w!iMZk(n2k=r57r?fHhYGG|BXPP$!dvqgkEz`Q@?(diBNj+)GLeFN2tX-kU;&j$!A2s`=OEw<tX+x(z)XO*+%sZ=m)t18M23P{2q*;BCnSV@eM+v46Fe#%x952er_z91H~DNVsS!fa;D|Ju32@<F!2fe40s$8oPac#h2Myt=&^VPKkYL@Jv0h=@lSeEl?o;vBAiQJh^?<b3!Q>Hx25*WQg^p52IVaH#;}pVhPA~#`N|A#9Bg`_M2FEZUObsZVYOMta?dH;A*#kfD1cdsOd}x&0QN?q6Ui)C;NhsfBEiL#B1Lj3xX$3$?kVU2-@{YN3XTgI53U}brt&+fPo@yaLHnq2sOQca>$=N!dyl4K{F~xL1=l$V8kxVyP&42}%7NQ|8bP}u&M-a;}$2kOu2tqK)Js?UEIOWDeJSjYcXDJ154f?K4Pu;0xe9isbnx1t`C^TS>)#0*4pzfQ39WM+ZF&{uIF|ZW@Qv;9{P_I)~Sn%KAY_wNWIiM-An2G?}lQIMU1>S$nk@Gc_e$OPR{U};hQ^lE7zL>O46n8UuyCyBWRN=8Rmdp8~1ae$Wx<}r5jE@EuLU{<$JOQ(Tn2rDC0Vp$%0oDiM3=I-90vHRY0)ajNP7tXg#1XSTrm2}Rbp}+=f?t%YWGIj{174TaSf-jR>w~3`_trwhVFVa^0ji}0*COUOjCBM;BLNW{V^tLN=X{#Sxl-+bsd)Tmc5$WuLEoS^^f1%1YDu{!9i^0)!Y~h%(T*#GAe^McF-4uz8i*HzAgi&9**BLG1114HKK0<(ARd;ey=gwpFK#B<>3LbbdiUW!&>O<v#2+?^?Mao`?gbNI(^F?4p7BJ0(rP0uECm6Nm{jmI;0=n0+=Aa>9&r*aCx@`jT96>rjDu@Mp<5XR|LLW~h=iCH;}ik3g76tR2QV7os*w;QW2SrzS`e}lKsHu^B2TP}xBZVRK+z`p;-c`e%Wg8yGx$4zzW^IhWc_hy#0Ub`2dECDXNE%rloC%;rkDok;h8lQf=ZA{1W1(_1>OomBrf3t6CCXxXXBn%)94dBKqg<Z&)EdjZBi-r#9a8v6`jDkSa(q?oBixHW&u+f2*nJ5ofAU9U)U=HupPmFgriadz9S4k2nDzam^d{=Kxio|Rcr2Dt$NYj8I%P;sbUa4gLuPjyycbw)<(){V3Gsv3qVXyH38;YrV*wX9;-N0ygHA!x$`xw6Aai)#|lWW#zDs_&$|}xO3!<br#N5^I7HesXt4G+1OnPcqRR&xOthigN7x5crYX~$3#(IjX(JHW>9zYe8eALB_Tw{}(l`bV>wt8MnN<Nf&Wx}DtU3qM5dap_2A#soh@d%U5T*qJFBXN<^&fHNOHhka_aYVsZr`y0o);(ussz#j;1Cqf!`lK-1fL9XAw0~0nE(=F2O&S;MNn0X!kP;xd;nvyCioDVhv-Ti6*2Y4kWmIyhy+iO1iK62WlBKmsm3TxK`0?wgDBn-B!E7W_itY_sK<K;*2*bFI88N0Twwq)l7gsNu$^#sfswO-B@~rbBQPWY!N9;P3C11pVmPX6XzpBhAPkz>*o=DA*)5w2EPy9SkX}#}><Bznfo<S2APJ%@Awpvobi2F9yqLs3$Pp6-ds~QqRRic2i;14cUgyTxgSV^x;j+bCm*AK?H*Kf+(uJum;$~bc37dXb_{!CT^@Wh(-rG4Jhn{Ty2Hew4HI{J0w+#aEfLGuFzAUmx{7t`{`vOEO-lhT*pxVp(U#BuW+kVsS#SZ)#0Mh{R=%gNIv+>7E1JrMD)ygq%_+ewls%_8vzy1Qu-T0h>-2YuGnh&h0lRT`z%oLjz^L6MD*;_wp=V``o&a4Q=TLGGvdT=BtbrcMMK_?H7pRMQ@g}Nr>&Z9ajM7y?ie9!33)>_pEpVt?l-siE2WvXu`vDdIN40T9wR(qGqIy3`T-P%1c0rF*6kp~sE>c>rU`x$=Nc&iHgegE#4AAb7b-KX=($KQYX^wZDhlk;ER{qz0#4=Y;y>*Ko*KTgj7=fnG7Kc0WQ=j&h2fB*RI{p92Mr;k6K{}=r0_RoI){r#t(e*E>r<mX?1IER(wAsW=~_sz!*(1Ndi`|;fmzy9~+xAULh!Fzpw>xN%r-{x)HKq&&x;8F&rUfP(cCk)&@M5)BZtfcnfX)&N`3I5(7PgwvX>;V}9+yX}ePrb^faLc^1!ao!GhQHw_$F7=aq^pTO8qQZ1wT2KCODkqQ7`eYC5G_9#K)q$?^x<p@gv4LtWEilP^}9!?w(4{}`G*bP8LhML0LYzPMc`NCy4(6ueR`&m@J4{Q2C%AQdKzG_!c^V4>@FwoyHr?8NN_xaRA^32nhLB_CL#DIT>D_aw|e8NM^u2fRR<KyLmI2ob|KV}P-h10vM8!K!5il6?%-9s8y4Oyv#Fc3?MD+GqEFB+Z)Q=~@?wh|{AP6hjVX+tCM(OHz3c$NWIv~U&#jt5{u8kJp*+h0Z=5Y>)yue(uNx!E!dsus?*^2UOI;7H`KyZyTO+n&uLN|>5kPM$ICC=Upi?#m7|Lr&0MSVv7$VY2VgSQ>Ze0+B(0~+!&|no0>UlPq>zip_Q=$QS4x&i~Dy;>Bh}i=4gs{&E49J&(<fNQo$~6}_h0rZ11b~l1sOt^ElvF7DDADG#3nCvamN`-=a3r+;3VdII@1q0X9Z>D9E02PcI!w|%us!FXhP-PTn92j+F(~jc?R~hYQ%CKOYfuZTXh%v^n6@2<wW9K(0?ey)a67Ft9#S#w<(C)Wn69JmUwebr1;^jsemRh$45$Y2b-R?>(JWSe`!17i1MXf}zi4qs<a7OPy~0LhL9@VyfKiwMGFpoZng@Qp51lryxM!Lr;h2#$MTCMW2gn58(`${vYXFK80xUlA3NwdniURmX<QR^15Gf}*jajad7`BB44VGP<E1?&Q^~7{dn6uh8cOar~R`)zX<N?h7wSQ%;&37SJdjd%>it7aYe|J0sWlWLqp6iceH5=YF>7$eQVaR6L>I}2re>&?8lv+E6zVJ!i{F<1Xq#X;>9Eh@5ojR(Mx_NYU8d^LLWk99yQ#=HvvCKOi<}&`2vz?F88B-B`bP<ZjIyE!J`X`O`CRiq|Wj;;nzRaZRJU>lp3zM|XF4e(0tAi-|Vzi++`lX4_>eQ!I^Zg;@XFz+&W5`cE#WyMQ_6*}$(i^{;RO7jtGd-(w6Psb_r%5xN>@?|`o+>Ho&3;)kN4LwupW@MUk79&Y;<R=a?fw!qq($s8B&s|8u(C$Y$vE*S*k-N|_^r0pJ6XL^(wt<|9bjCYfY@YQ`;v6GEdHe#q=(Lt-CvG|^zj{Ajy}fWJMAIEaX|U%gyB9)YG%lvCRHorX|fu=f0|Uobfe5=i)3|XLSKsR_5(b{V_c6ZMfaYIeNdb<q+j~@P`jO|+nh7l%&ScLL-(7LgjYm9P1cT<0RR=tqgUd0n)D|wR>rC~gQ72KYb_HmO~{S`y@!l$cnn8ZPj0DCQH{N+wY`dy7n8MPfqFKp7QaeZx~Bg%=XP&r$V+o_k7J&O%=LH-S?WY23P-p0R><lDvLZTv|NiIb*J?=KP+|kne#r=XU33m8ECVLa9p9IAqpFhCwCz<&s0rfMoLLOuAgXIpx5;V<Z(nL|_5QrNsr{v8$PA!kOUv)QVJJyEnmUOGyCw0|2oM{ew5OydaX?rXenlIzIvOvjw|<glVs2k@)_R>@G4$c$`5`mBjx9gut<k7AcG`%nIrnH4l!19^{82S-HOfw$qnOl3044P_#>8~8))$~#ZC)?UYaKV3A2QGB_%5s6pJ?1tH;6Q;HsRJzg0GHcI8E9?<aO4unpIUnqvrgoq!~Nb7o>-}++H2p0c2^wl)A^j%GHv4X~y2xN1Qa9)MurfCf$jmr>jI_(jO>Yrx;hKg(cO<=k+AfJxzWu%}A|s);))J0ErrMlJMh1U-b!L$!d0O9o5%`gGqA^LrgHPPQC1jRFtCb=+2}&SaS_v-|B9Bv72azm7oEQoJW_S536%8)*M-#>#5CBGatCw!B2XJKUUIH4Uev!TwiAHY2$p^+Z~-l`{VwSoOlO#8~fRp{hCZEH49Fq#!$|=LfRp31>?psX%uEDQ7Ew3iiCwlj06(A(*YxyGR8&}=ByRktTnhkr(UD}^|NJ^jFY!m^*?>Eg1HmQwsGQ0&%3IlUYUJWk@k1h-S<oBRz*kfrg4|3DLSg(Y^}CE-h97GqvjD4qZjc2w64pfYcj9i^rWf<ZR`BndcBD*%OW$&`rp?&o9e!0+q;Q=#F__`#yr0@M={&4oa3pk8IR@jfP#bP$7d?{-5h_aYo=q@JYWm=`K@`2Y!BFD{N`-ffW5HiXT!G0_JA#&Z%&^FY)m}AHE)sa0m<}lPPPZ+e!o3FZ_iPFb2w~37VVphF$Uy)p75Ig7~QwNA(CG2TyI*Lu7GMqrl;Be_1oW`XUAteY@pP=7O{=3YPTD?ZZ~nYy+<nwu86QP74evv2Lo?$d8Lcblf^Q&L-kt8xDAFtc)<yG#uIBbXH)>Mg4SGnO#rMQVFeBxLNBSj(gq8~9Tx%B=LYRE6zb0G0hill)x&ycpbt+4Mx4-U4nKGl#h3zX!-z&k7?2fsIRs%pP1C@=RGeUKr6wVz#CzW#l{@*rtk>F%jlfnY?`Qz49b?R3QeZSv8cEM}oEN33L{VTVks{7RV;a6zEPz8NqxAXtOj6jA|NVPLj~#uA7_g)#dkV-(5kV3Ip5eja*hm>zs+lJoe4v087_5CYsS@PHAe1tpQjp3No_yR9W&2w8m0h}J*dJl!*bv`w+_7ZGm>af(e~1Mbn<mSB{rdk7PpLc"
)


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _artifact_bytes(value: Any) -> bytes:
    return canonical_json_bytes(value) + b"\n"


def _artifact_sha(value: Any) -> str:
    return hashlib.sha256(_artifact_bytes(value)).hexdigest()


def _decoded_bundle() -> dict[str, dict[str, Any]]:
    value = json.loads(zlib.decompress(base64.b85decode(_BUNDLE_B85)))
    if not isinstance(value, dict):
        raise IntegrityError("candidate release bundle must be an object")
    return value


def build_candidate_release() -> dict[str, dict[str, Any]]:
    return copy.deepcopy(_decoded_bundle())


def validate_candidate_release(
    artifacts: Mapping[str, Mapping[str, object]],
) -> dict[str, Any]:
    required = set(_decoded_bundle())
    if set(artifacts) != required:
        raise IntegrityError("candidate release artifact set mismatch")

    source = artifacts["candidate-source-bundle.json"]
    if source.get("schema_version") != SOURCE_SCHEMA:
        raise IntegrityError("candidate source schema mismatch")
    if source.get("source_lane") != "evaluation-only-pending-proposal":
        raise IntegrityError("candidate source lane mismatch")
    concepts = source.get("concepts")
    if not isinstance(concepts, list) or len(concepts) != 15:
        raise IntegrityError("candidate concept count mismatch")
    candidate_ids: set[str] = set()
    anchors: set[str] = set()
    for item in concepts:
        if not isinstance(item, Mapping):
            raise IntegrityError("candidate concept must be an object")
        if RENDERER_FIELDS.intersection(item):
            raise IntegrityError("candidate concept contains renderer fields")
        candidate_id = item.get("candidate_id")
        anchor = item.get("semantic_anchor_graph_node_id")
        if not isinstance(candidate_id, str) or candidate_id in candidate_ids:
            raise IntegrityError("candidate identity is invalid or duplicated")
        if not isinstance(anchor, str):
            raise IntegrityError("candidate semantic anchor is invalid")
        candidate_ids.add(candidate_id)
        anchors.add(anchor)
        if item.get("decision") != "pending":
            raise IntegrityError("candidate review state drift")
        if item.get("status") != "pending-human-review":
            raise IntegrityError("candidate review state drift")
        for flag in (
            "canonical_knowledge",
            "candidate_release_eligible",
            "production_authority",
        ):
            if item.get(flag) is not False:
                raise IntegrityError(f"candidate {flag} must remain false")
    if anchors != set(EXPECTED_ANCHOR_COUNTS):
        raise IntegrityError("candidate semantic anchor set mismatch")

    graph = artifacts["candidate-graph-v2.json"]
    if graph.get("schema_version") != GRAPH_SCHEMA:
        raise IntegrityError("candidate graph schema mismatch")
    if graph.get("renderer_neutral") is not True:
        raise IntegrityError("candidate graph renderer neutrality mismatch")
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list) or len(nodes) != 15:
        raise IntegrityError("candidate graph node count mismatch")
    if not isinstance(edges, list) or len(edges) != 12:
        raise IntegrityError("candidate graph edge count mismatch")
    graph_ids = {
        node.get("concept_id") for node in nodes if isinstance(node, Mapping)
    }
    if graph_ids != candidate_ids:
        raise IntegrityError("candidate graph/source identity mismatch")
    edge_ids: set[str] = set()
    for edge in edges:
        if not isinstance(edge, Mapping):
            raise IntegrityError("candidate graph edge must be an object")
        edge_id = edge.get("edge_id")
        if not isinstance(edge_id, str) or edge_id in edge_ids:
            raise IntegrityError("candidate graph edge identity invalid or duplicated")
        if edge.get("source") not in candidate_ids:
            raise IntegrityError("candidate graph edge endpoint missing")
        if edge.get("target") not in candidate_ids:
            raise IntegrityError("candidate graph edge endpoint missing")
        edge_ids.add(edge_id)

    semantic = artifacts["semantic-reference.json"]
    if semantic.get("point_count") != 107:
        raise IntegrityError("semantic identity counts mismatch")
    if semantic.get("anchor_counts") != EXPECTED_ANCHOR_COUNTS:
        raise IntegrityError("semantic identity counts mismatch")
    if semantic.get("per_concept_section_attribution_available") is not False:
        raise IntegrityError("per-concept section attribution must not be claimed")
    if semantic.get("typed_graph_edges_are_semantic_edges") is not False:
        raise IntegrityError("typed graph edges cannot be semantic edges")
    mappings = artifacts["semantic-anchor-map.json"].get("mappings")
    if not isinstance(mappings, list) or len(mappings) != 15:
        raise IntegrityError("semantic anchor mapping count mismatch")
    mapped_ids = {
        item.get("candidate_id")
        for item in mappings
        if isinstance(item, Mapping)
    }
    if mapped_ids != candidate_ids:
        raise IntegrityError("semantic anchor mapping coverage mismatch")

    manifest = artifacts["candidate-release-manifest.json"]
    if manifest.get("schema_version") != RELEASE_SCHEMA:
        raise IntegrityError("candidate release schema mismatch")
    without_hash = dict(manifest)
    supplied_sha = without_hash.pop("manifest_sha256", None)
    actual_sha = hashlib.sha256(canonical_json_bytes(without_hash)).hexdigest()
    if supplied_sha != actual_sha:
        raise IntegrityError("candidate release self-digest mismatch")
    if manifest.get("immutable") is not True or manifest.get("read_only") is not True:
        raise IntegrityError("candidate release must be immutable and read-only")
    for flag in (
        "canonical_knowledge",
        "candidate_release_eligible",
        "production_authority",
    ):
        if manifest.get(flag) is not False:
            raise IntegrityError(f"candidate release {flag} must remain false")
    authority = manifest.get("authority")
    if not isinstance(authority, Mapping):
        raise IntegrityError("candidate release authority is missing")
    if any(value is not False for value in authority.values()):
        raise IntegrityError("candidate release authority must remain false")

    graph_api = artifacts["candidate-graph-api-payload.json"]
    release = graph_api.get("release")
    if graph_api.get("schema_version") != GRAPH_API_SCHEMA:
        raise IntegrityError("candidate Graph API payload mismatch")
    if graph_api.get("read_only") is not True:
        raise IntegrityError("candidate Graph API payload mismatch")
    if not isinstance(release, Mapping):
        raise IntegrityError("Graph API release identity missing")
    if release.get("release_id") != manifest.get("candidate_release_id"):
        raise IntegrityError("Graph API/candidate release identity mismatch")
    if release.get("manifest_sha256") != actual_sha:
        raise IntegrityError("Graph API/candidate manifest identity mismatch")

    overlay = artifacts["candidate-explorer-overlay.json"]
    if overlay.get("schema_version") != OVERLAY_SCHEMA:
        raise IntegrityError("candidate Explorer overlay schema mismatch")
    if overlay.get("feature_flag_default") is not False:
        raise IntegrityError("candidate Explorer feature boundary drift")
    if overlay.get("internal_only") is not True:
        raise IntegrityError("candidate Explorer internal boundary drift")
    if overlay.get("typed_graph_and_semantic_overlay_conflated") is not False:
        raise IntegrityError("typed graph and semantic overlay cannot be conflated")
    if overlay.get("node_level_semantic_counts_claimed") is not False:
        raise IntegrityError("node-level semantic counts are not evidenced")

    receipt = artifacts["candidate-release-receipt.json"]
    if receipt.get("status") != "pass" or receipt.get("external_mutations") != 0:
        raise IntegrityError("candidate release receipt is not an offline pass")
    return {
        "schema_version": "knowledge-engine-m23-candidate-release-acceptance/v1",
        "milestone": "M23.6.6",
        "status": "pass",
        "candidate_release_id": manifest["candidate_release_id"],
        "candidate_release_manifest_sha256": actual_sha,
        "artifact_hashes": {
            name: _artifact_sha(value)
            for name, value in sorted(artifacts.items())
        },
        "counts": {
            "candidate_concepts": 15,
            "typed_relations": 12,
            "semantic_sections": 107,
            "semantic_anchors": 3,
        },
        "semantic_anchor_counts": EXPECTED_ANCHOR_COUNTS,
        "production_retrieval_mode": "lexical",
        "graph_explorer_enabled_default": False,
        "external_mutations": 0,
    }


def load_contract(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise IntegrityError("candidate release contract must be an object")
    if value.get("schema_version") != CONTRACT_SCHEMA:
        raise IntegrityError("unsupported candidate release contract")
    return value


def write_candidate_release(output_dir: Path) -> dict[str, Any]:
    artifacts = build_candidate_release()
    report = validate_candidate_release(artifacts)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, value in artifacts.items():
        (output_dir / name).write_bytes(_artifact_bytes(value))
    (output_dir / "acceptance-report.json").write_bytes(_artifact_bytes(report))
    return report
