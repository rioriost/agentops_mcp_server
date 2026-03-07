class AgentopsMcpServer < Formula
  include Language::Python::Virtualenv

  desc "AgentOps MCP Server"
  homepage "https://github.com/rioriost/homebrew-agentops_mcp_server/"
  url "https://files.pythonhosted.org/packages/69/10/61ddb0e59d6c8017a8e81e157e2e38cc8505c5934bc7a5feb12c6806993b/agentops_mcp_server-0.4.3.tar.gz"
  sha256 "1fc8d8c3452bcafe8e93fab918360cc4aa8eb577073c5b884cc23ca54a4a2234"
  license "MIT"

  depends_on "python@3.14"

  def install
    virtualenv_install_with_resources
    prefix.install "README-jp.md"
    prefix.install "docs"
  end

  test do
    system "#{bin}/agentops_mcp_server", "--help"
  end
end
